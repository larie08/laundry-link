import pandas as pd
import io
from flask import Flask, render_template, request, redirect, url_for, session, flash, get_flashed_messages, send_file, jsonify, Response
import os
from werkzeug.utils import secure_filename
from dbhelper import *
import io
import pandas as pd
from fpdf import FPDF
from datetime import datetime, timedelta
import dbhelper
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from xlsxwriter.workbook import Workbook
import qrcode
import requests  # Use requests to forward to ESP32

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.secret_key = 'laundrylink'

# Jinja2 filter for formatting datetime
@app.template_filter('datetimeformat')
def datetimeformat(value, format='%B %d, %Y, %I:%M %p'):
    import datetime
    # Firestore timestamps may be strings or datetime objects
    if isinstance(value, str):
        try:
            # Try parsing ISO format
            dt = datetime.datetime.fromisoformat(value)
            return dt.strftime(format)
        except Exception:
            return value
    elif hasattr(value, 'strftime'):
        return value.strftime(format)
    return value

# Register built-in functions for Jinja2 templates
app.jinja_env.globals.update(max=max, min=min)

def get_price_per_load(order_type: str) -> float:
    """
    Return price per load based on service type.
    Self-service: 50; Drop-off (or others): 80.
    """
    norm = str(order_type or '').strip().lower().replace('_', '-')
    if 'drop' in norm:
        return 80.0
    return 50.0

# CUSTOMER ROUTES
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/service_type')
def service_type():
    return render_template('service.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    order_type = request.args.get("order_type") 
    if order_type:
        session['order_type'] = order_type  

    if request.method == 'POST':
        fullname = request.form['name']
        phone_number = request.form['contact']
        
        # Store customer data in session instead of saving to DB immediately
        session['customer_data'] = {
            'fullname': fullname,
            'phone_number': phone_number
        }
        
        return redirect(url_for('weight_laundry'))

    # Pre-fill form with session data if user goes back
    customer_data = session.get('customer_data', {})
    return render_template('contact.html', 
                         order_type=session.get('order_type'),
                         customer_name=customer_data.get('fullname', ''),
                         customer_phone=customer_data.get('phone_number', ''))



@app.route('/weight_laundry', methods=['GET', 'POST'])
def weight_laundry():
    global weight_page_active
    
    # Check if customer data exists in session
    if 'customer_data' not in session:
        flash('Please provide customer information first.')
        return redirect(url_for('contact'))
    
    if request.method == 'POST':
        weight_page_active = False  # User leaving page
        weight_str = request.form.get('weight', '')
        total_load_str = request.form.get('total_load', '')
        try:
            weight = float(weight_str) if weight_str else 0.0
        except ValueError:
            weight = 0.0
        try:
            # Extract numeric value from "Load(s): X" format
            if 'Load(s):' in total_load_str:
                total_load = int(total_load_str.split(':')[1].strip())
            else:
                total_load = int(total_load_str) if total_load_str else 0
        except (ValueError, IndexError):
            total_load = 0
        session['total_weight'] = weight
        session['total_load'] = total_load
        return redirect(url_for('other_services'))
    
    weight_page_active = True  # User is on page
    # Pre-fill with session data if user goes back
    return render_template('weight.html',
                         weight=session.get('total_weight', ''),
                         total_load=session.get('total_load', ''))

@app.route('/other_services')
def other_services():
    detergents = get_all_detergents()
    fabric_conditioners = get_all_fabric_conditioners()
    order_type = session.get('order_type', 'Drop-off')
    return render_template('others.html', detergents=detergents, fabric_conditioners=fabric_conditioners, order_type=order_type)

@app.route('/submit_others', methods=['POST'])
def submit_others():
    # Check if customer and weight data exists in session
    if 'customer_data' not in session:
        flash('Please provide customer information first.')
        return redirect(url_for('contact'))
    if 'total_weight' not in session or 'total_load' not in session:
        flash('Please provide weight and load information first.')
        return redirect(url_for('weight_laundry'))
    
    # Get form data
    detergent_ids = request.form.getlist('detergent_ids')
    fabcon_ids = request.form.getlist('fabcon_ids')
    own_detergent = request.form.get('own_detergent') == '1'
    own_fabcon = request.form.get('own_fabcon') == '1'
    iron = request.form.get('iron') == '1'
    fold = request.form.get('fold') == '1'
    priority = request.form.get('priority') == '1'
    
    # Get order note and pickup schedule from hidden inputs
    order_note = request.form.get('order_note', '').strip()
    pickup_date = request.form.get('pickup_date', '').strip()
    pickup_time = request.form.get('pickup_time', '').strip()
    
    # Combine pickup date and time into SQL datetime format
    pickup_schedule = None
    if pickup_date and pickup_time:
        pickup_schedule = f"{pickup_date} {pickup_time}:00"
    elif pickup_date:
        pickup_schedule = f"{pickup_date} 00:00:00"
    
    # If order_note is empty, set to None
    if not order_note:
        order_note = None

    # Get weight and load from session
    total_weight = session.get('total_weight', 0.0)
    total_load = session.get('total_load', 0)
    price_per_load = get_price_per_load(session.get('order_type', 'Drop-off'))

    # Calculate subtotal
    subtotal = 0.0

    # Load price (50 per load)
    subtotal += total_load * price_per_load

    # Store detergent details
    detergent_details = []
    if not own_detergent:
        for det_id in detergent_ids:
            qty = int(request.form.get(f'detergent_qty_{det_id}', 1))
            price = float(request.form.get(f'detergent_price_{det_id}', 0))
            detergent_details.append({
                'detergent_id': int(det_id),
                'quantity': qty,
                'unit_price': price
            })
            subtotal += qty * price

    # Store fabcon details
    fabcon_details = []
    if not own_fabcon:
        for fab_id in fabcon_ids:
            qty = int(request.form.get(f'fabcon_qty_{fab_id}', 1))
            price = float(request.form.get(f'fabcon_price_{fab_id}', 0))
            fabcon_details.append({
                'fabcon_id': int(fab_id),
                'quantity': qty,
                'unit_price': price
            })
            subtotal += qty * price

    # Additional service costs
    if iron:
        subtotal += 50.00
    if fold:
        subtotal += 70.00
    if priority:
        subtotal += 50.00
    
    # Calculate tax and total
    tax = round(subtotal * 0.12, 2)  # 12% VAT
    total_price = round(subtotal + tax, 2)
    
    # Store all order data in session instead of saving to DB
    session['order_data'] = {
        'order_type': session.get('order_type', 'Drop-off'),
        'total_weight': total_weight,
        'total_load': total_load,
        'subtotal': round(subtotal, 2),
        'tax': tax,
        'total_price': total_price,
        'price_per_load': price_per_load,
        'order_note': order_note,
        'pickup_schedule': pickup_schedule,
        'own_detergent': own_detergent,
        'own_fabcon': own_fabcon,
        'iron': iron,
        'fold': fold,
        'priority': priority,
        'detergent_details': detergent_details,
        'fabcon_details': fabcon_details
    }

    return redirect(url_for('payments'))

@app.route('/payments', methods=['GET', 'POST'])
def payments():
    if request.method == 'POST':
        # Check if all required session data exists
        if 'customer_data' not in session or 'order_data' not in session:
            flash('Order data is missing. Please start from the beginning.')
            return redirect(url_for('contact'))
        
        payment_method = request.form.get('payment_method')
        
        # NOW save everything to database when payment is confirmed
        customer_data = session.get('customer_data')
        order_data = session.get('order_data')
        
        # Save customer to database
        customer_id = None
        # Check if customer already exists
        existing_customers = dbhelper.get_all_customers()
        for cust in existing_customers:
            if cust.get('FULLNAME') == customer_data['fullname'] and cust.get('PHONE_NUMBER') == customer_data['phone_number']:
                customer_id = cust['CUSTOMER_ID']
                break
        
        # If customer doesn't exist, create new one
        if customer_id is None:
            dbhelper.add_customer(customer_data['fullname'], customer_data['phone_number'])
            # Get the newly created customer
            latest_customer = dbhelper.get_latest_customer()
            if latest_customer:
                customer_id = latest_customer['CUSTOMER_ID']
            else:
                flash('Error creating customer. Please try again.')
                return redirect(url_for('contact'))
        else:
            latest_customer = dbhelper.get_customer_by_id(customer_id)
        
        # Create ORDER_ITEM
        orderitem_id = dbhelper.add_order_item(
            order_data['own_detergent'],
            order_data['own_fabcon'],
            order_data['iron'],
            order_data['fold'],
            order_data['priority']
        )
        
        # Add detergents to junction table
        if not order_data['own_detergent']:
            for det in order_data['detergent_details']:
                dbhelper.add_orderitem_detergent(
                    orderitem_id,
                    det['detergent_id'],
                    det['quantity'],
                    det['unit_price']
                )
                # Deduct detergent quantity from inventory when order is placed
                dbhelper.deduct_detergent_quantity(det['detergent_id'], det['quantity'])


        # Add fabcons to junction table
        if not order_data['own_fabcon']:
            for fab in order_data['fabcon_details']:
                dbhelper.add_orderitem_fabcon(
                    orderitem_id,
                    fab['fabcon_id'],
                    fab['quantity'],
                    fab['unit_price']
                )
                # Deduct fabric conditioner quantity from inventory
                dbhelper.deduct_fabcon_quantity(fab['fabcon_id'], fab['quantity'])

        
        # Create ORDER record
        order_status_value = 'Completed' if str(order_data.get('order_type', '')).lower() == 'self-service' else 'Pending'
        order_id = dbhelper.add_order(
            customer_id=customer_id,
            orderitem_id=orderitem_id,
            user_id=None,
            order_type=order_data['order_type'],
            total_weight=order_data['total_weight'],
            total_load=order_data['total_load'],
            total_price=order_data['total_price'],
            tax=order_data.get('tax', 0.0),
            order_note=order_data['order_note'],
            pickup_schedule=order_data['pickup_schedule'],
            order_status=order_status_value,
            payment_method=payment_method,
            payment_status='Pending'
        )
        
        # Generate QR code
        qr_img = qrcode.make(str(order_id))
        qr_filename = f"qr_order_{order_id}.png"
        qr_filepath = os.path.join(app.static_folder, "qr", qr_filename)
        os.makedirs(os.path.dirname(qr_filepath), exist_ok=True)
        qr_img.save(qr_filepath)
        qr_code_path = f"qr/{qr_filename}"
        dbhelper.update_order_qr_code(order_id, qr_code_path)

        # Receipt printing for all payment methods - ONLY PRINT ORDER ID
        if payment_method and payment_method.lower() in ['cash', 'gcash', 'maya']:
            try:
                from escpos.printer import Usb
                from PIL import Image, ImageDraw, ImageFont
                p = Usb(0x0483, 0x5743, encoding='GB18030')

                order = dbhelper.get_order_by_id(order_id)

                # Create a custom image with logo and Order ID side-by-side
                logo_path = os.path.join(app.static_folder, 'images', 'logo.jpg')
                if os.path.exists(logo_path):
                    # Open logo image
                    logo_img = Image.open(logo_path)
                    logo_img = logo_img.resize((150, 150))  # Resize logo
                    
                    # Create new image for receipt with logo and Order ID
                    receipt_width = 400
                    receipt_height = 180
                    receipt_img = Image.new('RGB', (receipt_width, receipt_height), 'white')
                    
                    # Paste logo on left side
                    receipt_img.paste(logo_img, (10, 15))
                    
                    # Add Order ID text on right side with larger font
                    draw = ImageDraw.Draw(receipt_img)
                    try:
                        # Try to use a larger bold font
                        font = ImageFont.truetype("arialbd.ttf", 40)
                    except:
                        try:
                            # Fallback to regular arial
                            font = ImageFont.truetype("arial.ttf", 40)
                        except:
                            # Fallback to default font
                            font = ImageFont.load_default()
                    
                    order_id_text = f"Order ID:\n{order.get('ORDER_ID')}"
                    draw.text((170, 40), order_id_text, fill='black', font=font)
                    
                    # Print the combined image
                    p.image(receipt_img)
                    p.text("\n")
                else:
                    # Fallback: print Order ID with large font if logo not found
                    p.set(height=2, width=2)  # Large font
                    p.text(f"Order ID: {order.get('ORDER_ID')}\n")
                    p.set(height=1, width=1)  # Reset font

                # CLOSE printer connection to free it up for mark_order_as_paid()
                p.close()
            except Exception as e:
                print("Printer error:", e)
        
        # Clear session data after successful order creation
        session.pop('customer_data', None)
        session.pop('order_data', None)
        session.pop('total_weight', None)
        session.pop('total_load', None)
        session.pop('order_type', None)
        
        # If the request came from an AJAX call (QR flows), return JSON for client-side redirect
        if request.args.get('ajax') == '1' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True,
                'order_id': order_id,
                'redirect': url_for('thank_you_page', order_id=order_id)
            })

        return redirect(url_for('thank_you_page', order_id=order_id))
    
    # GET request - display payment page using session data
    # Check if all required session data exists
    if 'customer_data' not in session:
        flash('Please provide customer information first.')
        return redirect(url_for('contact'))
    if 'order_data' not in session:
        flash('Please complete order details first.')
        return redirect(url_for('other_services'))
    
    customer_data = session.get('customer_data')
    order_data = session.get('order_data')
    
    # Create customer dict for template
    customer = {
        'FULLNAME': customer_data['fullname'],
        'PHONE_NUMBER': customer_data['phone_number']
    }
    
    # Create order dict for template
    order_status_value = 'Completed' if str(order_data.get('order_type', '')).lower() == 'self-service' else 'Pending'
    order = {
        'ORDER_ID': 'Pending',  # Will be assigned when saved
        'ORDER_TYPE': order_data['order_type'],
        'ORDER_STATUS': order_status_value,
        'PAYMENT_STATUS': 'Unpaid',
        'TOTAL_WEIGHT': order_data['total_weight'],
        'TOTAL_LOAD': order_data['total_load'],
        'TOTAL_PRICE': order_data['total_price'],
        'ORDER_NOTE': order_data['order_note'],
        'PICKUP_SCHEDULE': order_data['pickup_schedule']
    }
    
    # Create orderitem dict for template
    orderitem = {
        'CUSTOMER_OWN_DETERGENT': order_data['own_detergent'],
        'CUSTOMER_OWN_FABCON': order_data['own_fabcon'],
        'IRON': order_data['iron'],
        'FOLD_CLOTHES': order_data['fold'],
        'PRIORITIZE_ORDER': order_data['priority']
    }
    
    # Calculate load price based on service type
    price_per_load = get_price_per_load(order_data['order_type'])
    load_price = order_data['total_load'] * price_per_load
    
    # Get detergent and fabcon details for display
    orderitem_detergents = []
    if not order_data['own_detergent']:
        for det in order_data['detergent_details']:
            detergent = dbhelper.get_detergent_by_id(det['detergent_id'])
            if detergent:
                orderitem_detergents.append({
                    'DETERGENT_NAME': detergent.get('DETERGENT_NAME', 'Unknown'),
                    'QUANTITY': det['quantity'],
                    'UNIT_PRICE': det['unit_price'],
                    'total_price': det['quantity'] * det['unit_price']
                })
    
    orderitem_fabcons = []
    if not order_data['own_fabcon']:
        for fab in order_data['fabcon_details']:
            fabcon = dbhelper.get_fabric_conditioner_by_id(fab['fabcon_id'])
            if fabcon:
                orderitem_fabcons.append({
                    'FABCON_NAME': fabcon.get('FABCON_NAME', 'Unknown'),
                    'QUANTITY': fab['quantity'],
                    'UNIT_PRICE': fab['unit_price'],
                    'total_price': fab['quantity'] * fab['unit_price']
                })
    
    # Format the current date
    current_date = datetime.now().strftime('%B %d, %Y')
    
    # Format pickup schedule
    pickup_schedule_formatted = None
    pickup_schedule = order_data.get('pickup_schedule')
    if pickup_schedule:
        try:
            if isinstance(pickup_schedule, str):
                try:
                    pickup_dt = datetime.strptime(pickup_schedule, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pickup_dt = datetime.strptime(pickup_schedule, '%Y-%m-%d')
                pickup_schedule_formatted = pickup_dt.strftime('%B %d, %Y %I:%M %p')
        except Exception:
            pickup_schedule_formatted = str(pickup_schedule)

    return render_template('payments.html',
                         order=order,
                         customer=customer,
                         orderitem=orderitem,
                         price_per_load=price_per_load,
                         load_price=load_price,
                         orderitem_detergents=orderitem_detergents,
                         orderitem_fabcons=orderitem_fabcons,
                         current_date=current_date,
                         qr_code_path=None,  # No QR code until order is saved
                         pickup_schedule_formatted=pickup_schedule_formatted)

@app.route('/save_order_note', methods=['POST'], endpoint='save_order_note')
def save_order_note():
    """Save order note to session (order not created until payment confirmation)."""
    if 'order_data' not in session:
        return jsonify({'success': False, 'message': 'No order data found'}), 400
    
    order_note = request.form.get('order_note', '').strip()
    
    # Update order note in session
    if 'order_data' in session:
        session['order_data']['order_note'] = order_note if order_note else None
        session.modified = True
    
        return jsonify({'success': True, 'message': 'Note saved successfully'})
    
@app.route('/thank_you')
def thank_you_page():
    order_id = request.args.get('order_id')
    return render_template('thank_you.html', order_id=order_id)


@app.route('/new_order', methods=['GET'])
def new_order():
    """Backward-compatible route that now points to the thank you page."""
    order_id = request.args.get('order_id', 'N/A')
    return redirect(url_for('thank_you_page', order_id=order_id))





# ADMIN LOGIN
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = authenticate_user(username, password)
        if user and user['ROLE'].lower() == 'admin':
            session['user_id'] = user['USER_ID']
            session['username'] = user['USERNAME']
            session['role'] = user['ROLE']
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password, or not an admin account.', 'danger')
            return redirect(url_for('admin_login'))
    return render_template('admin_login.html', error=error)

# STAFF LOGIN
@app.route('/staff_login', methods=['GET', 'POST'])
def staff_login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = authenticate_user(username, password)
        if user and user['ROLE'].lower() == 'staff':
            session['user_id'] = user['USER_ID']
            session['username'] = user['USERNAME']
            session['role'] = user['ROLE']
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password, or not a staff account.', 'danger')
            return redirect(url_for('staff_login'))
    return render_template('staff_login.html', error=error)

# ADMIN FORGET PASSWORD
@app.route('/reset_admin_password', methods=['POST'])
def reset_admin_password():
    username = request.form.get('username', '').strip()
    old_password = request.form.get('old_password', '').strip()
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()
    
    # Validate passwords match
    if new_password != confirm_password:
        flash('New password and confirm password do not match!', 'danger')
        return redirect(url_for('admin_login'))
    
    # Authenticate user with old password
    user = authenticate_user(username, old_password)
    
    if not user:
        flash('Invalid username or password!', 'danger')
        return redirect(url_for('admin_login'))
    
    # Check if user is admin
    if user['ROLE'].lower() != 'admin':
        flash('Only admin accounts can reset password from this page.', 'danger')
        return redirect(url_for('admin_login'))
    
    # Update the password
    try:
        update_user(user['USER_ID'], username, new_password, user['ROLE'], user.get('FULLNAME', ''))
        flash('Password has been reset successfully! Please login with your new password.', 'success')
        return redirect(url_for('admin_login'))
    except Exception as e:
        flash(f'Error resetting password: {str(e)}', 'danger')
        return redirect(url_for('admin_login'))

# STAFF FORGET PASSWORD
@app.route('/reset_staff_password', methods=['POST'])
def reset_staff_password():
    username = request.form.get('username', '').strip()
    old_password = request.form.get('old_password', '').strip()
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()
    
    # Validate passwords match
    if new_password != confirm_password:
        flash('New password and confirm password do not match!', 'danger')
        return redirect(url_for('staff_login'))
    
    # Authenticate user with old password
    user = authenticate_user(username, old_password)
    
    if not user:
        flash('Invalid username or password!', 'danger')
        return redirect(url_for('staff_login'))
    
    # Check if user is staff
    if user['ROLE'].lower() != 'staff':
        flash('Only staff accounts can reset password from this page.', 'danger')
        return redirect(url_for('staff_login'))
    
    # Update the password
    try:
        update_user(user['USER_ID'], username, new_password, user['ROLE'], user.get('FULLNAME', ''))
        flash('Password has been reset successfully! Please login with your new password.', 'success')
        return redirect(url_for('staff_login'))
    except Exception as e:
        flash(f'Error resetting password: {str(e)}', 'danger')
        return redirect(url_for('staff_login'))

# ADMIN AND STAFF
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return redirect(url_for('admin_login'))

    detergents = get_all_detergents()
    fabric_conditioners = get_all_fabric_conditioners()

    low_detergents = [d for d in detergents if d['QTY'] <= 10]
    low_fabcons = [f for f in fabric_conditioners if f['QTY'] <= 10]

    # Get all orders with full details for dashboard
    all_orders = dbhelper.get_all_orders_with_priority()
    
    # Format time for display - data already includes TOTAL_LOAD, TOTAL_PRICE, etc.
    orders_with_details = []
    for order in all_orders:
        date_created = order.get('DATE_CREATED')
        # Format time for display
        if date_created and hasattr(date_created, 'strftime'):
            order['TIME_FORMATTED'] = date_created.strftime('%I:%M %p')
        else:
            order['TIME_FORMATTED'] = 'N/A'
        # Ensure defaults for missing values
        order['TOTAL_LOAD'] = order.get('TOTAL_LOAD', 0)
        order['TOTAL_PRICE'] = order.get('TOTAL_PRICE', 0.0)
        orders_with_details.append(order)
    
    # Separate orders into priority orders and self-service orders
    # Priority is determined by the 'PRIORITY' field provided by
    # dbhelper.get_all_orders_with_priority() (values: 'Priority' or 'Normal').
    priority_orders = [o for o in orders_with_details if str(o.get('PRIORITY', '')).lower() == 'priority']
    # Robustly detect self-service orders (tolerate casing and minor format variations)
    def is_self_service(o):
        t = str(o.get('ORDER_TYPE', '') or '').lower().replace(' ', '').replace('_', '')
        return 'selfservice' in t or t == 'self-service' or 'self' == t

    self_service_orders = [o for o in orders_with_details if is_self_service(o)]
    
    # Limit to 5 most recent for each section
    priority_orders = priority_orders[:5]
    self_service_orders = self_service_orders[:5]
    
    # Calculate statistics
    total_orders = len(orders_with_details)
    # Only count today's self-service and drop-off orders
    today = datetime.now().date()
    self_service_count = len([
        o for o in orders_with_details
        if o.get('ORDER_TYPE', '').lower() == 'self-service'
        and o.get('DATE_CREATED') and (
            o.get('DATE_CREATED').date() if hasattr(o.get('DATE_CREATED'), 'date') else o.get('DATE_CREATED')
        ) == today
    ])
    drop_off_count = len([
        o for o in orders_with_details
        if o.get('ORDER_TYPE', '').lower() == 'drop-off'
        and o.get('DATE_CREATED') and (
            o.get('DATE_CREATED').date() if hasattr(o.get('DATE_CREATED'), 'date') else o.get('DATE_CREATED')
        ) == today
    ])
    pending_count = len([o for o in orders_with_details if (o.get('ORDER_STATUS') or '').lower() == 'pending'])
    pickup_count = len([o for o in orders_with_details if (o.get('ORDER_STATUS') or '').lower() == 'pickup'])
    completed_count = len([o for o in orders_with_details if (o.get('ORDER_STATUS') or '').lower() == 'completed'])
    
    # Calculate today's sales (sum of TOTAL_PRICE for orders created today)
    today = datetime.now().date()
    todays_sales = 0.0
    
    # Calculate monthly earnings (sum of TOTAL_PRICE for orders created this month)
    current_month = datetime.now().month
    current_year = datetime.now().year
    monthly_earnings = 0.0
    
    for order in orders_with_details:
        date_created = order.get('DATE_CREATED')
        if date_created:
            # Handle both datetime objects and date objects
            if hasattr(date_created, 'date'):
                order_date = date_created.date()
            else:
                order_date = date_created
            
            order_price = float(order.get('TOTAL_PRICE', 0.0))
            
            if order_date == today:
                todays_sales += order_price
            
            # Check if order is from current month and year
            if order_date.month == current_month and order_date.year == current_year:
                monthly_earnings += order_price

    # Build datasets for charts (order status/type counts + short-term trend)
    order_stats = dbhelper.compute_order_stats(orders_with_details, days=7)
    order_status_counts = order_stats.get('status_counts', {})
    order_type_counts = order_stats.get('type_counts', {})
    order_trend = order_stats.get('trend', {'labels': [], 'counts': []})

    # BASED ON ROLE
    template_name = 'admin_dashboard.html' if session['role'] == 'admin' else 'staff_dashboard.html'

    return render_template(template_name,
        low_detergents=low_detergents,
        low_fabcons=low_fabcons,
        priority_orders=priority_orders,
        self_service_orders=self_service_orders,
        total_orders=total_orders,
        self_service_count=self_service_count,
        drop_off_count=drop_off_count,
        pending_count=pending_count,
        pickup_count=pickup_count,
        completed_count=completed_count,
        todays_sales=todays_sales,
        monthly_earnings=monthly_earnings,
        order_status_counts=order_status_counts,
        order_type_counts=order_type_counts,
        order_trend=order_trend
    )

# ADMIN AND STAFF
@app.route('/detergent_inventory', methods=['GET', 'POST'])
def detergent_inventory():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        action = request.form.get('action', 'Add')
        user_id = session.get('user_id')

        if action == 'Add' or action == 'Update':
            name = request.form['name']
            price = float(request.form['price'])
            quantity = int(request.form['quantity'])
            image = request.files.get('image')
            filename = None

            if image and image.filename:
                filename = secure_filename(image.filename)
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            if action == 'Add':
                add_detergent(name, price, quantity, filename, user_id=user_id)
            elif action == 'Update':
                detergent_id = int(request.form['detergent_id'])
                if not filename:
                    old = get_detergent_by_id(detergent_id)
                    filename = old['IMAGE_FILENAME'] if old else None
                update_detergent(detergent_id, name, price, quantity, filename, user_id=user_id)

        elif action == 'Delete':
            detergent_id = int(request.form['detergent_id'])
            user_id = session.get('user_id')
            delete_detergent(detergent_id, user_id=user_id)

        return redirect(url_for('detergent_inventory'))

    # SEARCH
    search_query = request.args.get('q', '').strip()
    if search_query:
        detergents = search_detergents(search_query)
    else:
        detergents = get_all_detergents()
    
    # PAGINATION
    page = request.args.get('page', 1, type=int)
    per_page = 5
    total_items = len(detergents)
    total_pages = (total_items + per_page - 1) // per_page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    current_items = detergents[start_idx:end_idx]
    
    # LOW STOCK DETERGENTS
    low_stock_detergents = [d for d in detergents if d['QTY'] <= 10]
    
    # TOTAL DETERGENTS
    low_stock_count = len(low_stock_detergents)
    out_of_stock_count = len([d for d in detergents if d['QTY'] == 0])
    
    
    # TOTAL INVENTORY VALUE
    total_value = sum(d['DETERGENT_PRICE'] * d['QTY'] for d in detergents)
    
    # BASED ON ROLE
    template_name = 'admin_detergent_inventory.html' if session['role'] == 'admin' else 'staff_detergent_inventory.html'
    
    return render_template(template_name, 
                         detergents=current_items,
                         current_page=page,
                         total_pages=total_pages,
                         low_stock_detergents=low_stock_detergents,
                         total_items=total_items,
                         low_stock_count=low_stock_count,
                         out_of_stock_count=out_of_stock_count,
                         total_value=total_value)

# ADMIN AND STAFF
@app.route('/fabric_conditioner', methods=['GET', 'POST'])
def fabric_conditioner():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        action = request.form.get('action', 'Add')
        user_id = session.get('user_id')

        if action == 'Add' or action == 'Update':
            name = request.form['name']
            price = float(request.form['price'])
            quantity = int(request.form['quantity'])
            image = request.files.get('image')
            filename = None

            if image and image.filename:
                filename = secure_filename(image.filename)
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            if action == 'Add':
                add_fabric_conditioner(name, price, quantity, filename, user_id=user_id)
            elif action == 'Update':
                fabcon_id = int(request.form['fabric_conditioner_id'])
                if not filename:
                    old = get_fabric_conditioner_by_id(fabcon_id)
                    filename = old['IMAGE_FILENAME'] if old else None
                update_fabric_conditioner(fabcon_id, name, price, quantity, filename, user_id=user_id)

        elif action == 'Delete':
            fabcon_id = int(request.form['fabric_conditioner_id'])
            user_id = session.get('user_id')
            delete_fabric_conditioner(fabcon_id, user_id=user_id)

        return redirect(url_for('fabric_conditioner'))

    # SEARCH
    search_query = request.args.get('q', '').strip()
    if search_query:
        fabric_conditioners = search_fabric_conditioners(search_query)
    else:
        fabric_conditioners = get_all_fabric_conditioners()
    
    # PAGINATION
    page = request.args.get('page', 1, type=int)
    per_page = 5
    total_items = len(fabric_conditioners)
    total_pages = (total_items + per_page - 1) // per_page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    current_items = fabric_conditioners[start_idx:end_idx]
    
    # Get total inventory value
    total_value = get_fabcon_total_value()['TotalValue']
    
    # Calculate additional statistics
    low_stock_count = len([f for f in fabric_conditioners if f['QTY'] <= 10])
    out_of_stock_count = len([f for f in fabric_conditioners if f['QTY'] == 0])
    
    # BASED ON ROLE
    template_name = 'admin_fabric_conditioner.html' if session['role'] == 'admin' else 'staff_fabric_conditioner.html'
    
    return render_template(template_name,
        fabric_conditioners=current_items,
        total_items=total_items,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count,
        total_value=total_value,
        current_page=page,
        total_pages=total_pages
    )

# ADMIN AND STAFF
@app.route('/scanner')
def scanner():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return redirect(url_for('admin_login'))
    
    # Get all orders with ORDER_STATUS "Pick-up"
    orders = dbhelper.get_all_orders_with_priority()
    pickup_orders = [o for o in orders if (o.get('ORDER_STATUS', '').lower() == 'pick-up')]
    
    # BASED ON ROLE
    template_name = 'admin_scanner.html' if session['role'] == 'admin' else 'staff_scanner.html'
    return render_template(template_name, pickup_orders=pickup_orders)


# ADMIN AND STAFF
@app.route('/customers')
def customers():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return redirect(url_for('admin_login'))
    
    # Get customers with their orders
    customers_data = get_customers_with_orders()

    # Keep only customers whose latest order is not completed (pending or pick-up)
    def _norm_status(val: str) -> str:
        if not val:
            return ''
        s = str(val).strip().lower().replace('_', '-')
        # Normalize pickup variations
        if s == 'pickup':
            s = 'pick-up'
        return s

    customers_data = [
        c for c in customers_data
        if _norm_status(c.get('ORDER_STATUS')) in ['pending', 'pick-up']
    ]
    
    # Get statistics
    stats = get_customer_statistics()
    
    # Filter by search query if provided
    search_query = request.args.get('q', '').strip().lower()
    if search_query:
        customers_data = [c for c in customers_data if 
            search_query in str(c['CUSTOMER_ID']).lower() or
            search_query in c['FULLNAME'].lower() or
            (c['PHONE_NUMBER'] and search_query in c['PHONE_NUMBER'].lower())]
    
    # Filter by order status (pending / pick-up) if provided
    status_filter = request.args.get('status', '').strip().lower()
    if status_filter:
        customers_data = [
            c for c in customers_data
            if _norm_status(c.get('ORDER_STATUS')) == status_filter
        ]
    
    # PAGINATION
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Number of items per page
    total_items = len(customers_data)
    total_pages = (total_items + per_page - 1) // per_page  # Ceiling division
    
    # Ensure page is within valid range
    page = max(1, min(page, total_pages)) if total_pages > 0 else 1
    
    # Slice the data for current page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_customers = customers_data[start_idx:end_idx]
    
    # BASED ON ROLE
    template_name = 'admin_customers.html' if session['role'] == 'admin' else 'staff_customers.html'
    return render_template(template_name, 
                         customers=paginated_customers,
                         stats=stats,
                         current_page=page,
                         total_pages=total_pages)

# ADMIN AND STAFF - Edit Customer Routes
@app.route('/get_customer/<int:customer_id>', methods=['GET'])
def get_customer(customer_id):
    """Get customer data for editing."""
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return jsonify({'error': 'Unauthorized'}), 401
    
    customer = dbhelper.get_customer_by_id(customer_id)
    if not customer:
        return jsonify({'error': 'Customer not found'}), 404
    
    return jsonify({
        'CUSTOMER_ID': customer.get('CUSTOMER_ID'),
        'FULLNAME': customer.get('FULLNAME', ''),
        'PHONE_NUMBER': customer.get('PHONE_NUMBER', '')
    })

@app.route('/edit_customer', methods=['POST'])
def edit_customer():
    """Update customer information."""
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        customer_id = int(request.form.get('customer_id'))
        fullname = request.form.get('fullname', '').strip()
        phone_number = request.form.get('phone_number', '').strip()
        user_id = session.get('user_id')  # <-- Get current user ID

        if not fullname:
            return jsonify({'error': 'Full name is required'}), 400

        # Pass user_id to log the update
        success = dbhelper.update_customer(customer_id, fullname, phone_number, user_id=user_id)
        if success:
            return jsonify({'success': True, 'message': 'Customer updated successfully'})
        else:
            return jsonify({'error': 'Customer not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ADMIN AND STAFF
@app.route('/orders')
def orders():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return redirect(url_for('admin_login'))
    
    orders_data = dbhelper.get_all_orders_with_priority()

    # Show only orders that are pending or not yet paid.
    def _is_pending_or_unpaid(o):
        status = (o.get('ORDER_STATUS') or '').strip().lower()
        payment = (o.get('PAYMENT_STATUS') or '').strip().lower()
        return status == 'pending' or payment != 'paid'

    orders_data = [o for o in orders_data if _is_pending_or_unpaid(o)]

    # Filtering
    order_type = request.args.get('order_type', '').strip().lower()
    order_status = request.args.get('order_status', '').strip().lower()
    search_query = request.args.get('q', '').strip().lower()

    filtered_orders = orders_data
    if order_type:
        filtered_orders = [o for o in filtered_orders if (o['ORDER_TYPE'] or '').lower() == order_type]
    if order_status:
        filtered_orders = [o for o in filtered_orders if (o['ORDER_STATUS'] or '').lower() == order_status]
    if search_query:
        filtered_orders = [
            o for o in filtered_orders
            if search_query in str(o['ORDER_ID']).lower()
            or search_query in str(o['CUSTOMER_ID']).lower()
            or search_query in (o['CUSTOMER_NAME'] or '').lower()
        ]

    # Compute stats for charts
    priority_count = sum(1 for o in filtered_orders if o['PRIORITY'] == 'Priority')
    normal_count = sum(1 for o in filtered_orders if o['PRIORITY'] == 'Normal')
    pending_count = sum(1 for o in filtered_orders if (o['ORDER_STATUS'] or '').lower() == 'pending')
    pickup_count = sum(1 for o in filtered_orders if (o['ORDER_STATUS'] or '').lower() == 'pickup')
    completed_count = sum(1 for o in filtered_orders if (o['ORDER_STATUS'] or '').lower() == 'completed')
    stats = {
        'priority_count': priority_count,
        'normal_count': normal_count,
        'pending_count': pending_count,
        'pickup_count': pickup_count,
        'completed_count': completed_count
    }

    # PAGINATION
    items_per_page = 10
    page = request.args.get('page', 1, type=int)
    total_orders = len(filtered_orders)
    total_pages = (total_orders + items_per_page - 1) // items_per_page if total_orders > 0 else 1
    
    # Ensure page is within valid range
    if page < 1:
        page = 1
    elif page > total_pages and total_pages > 0:
        page = total_pages
    
    # Calculate start and end indices
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    paginated_orders = filtered_orders[start_idx:end_idx]

    # --- Add this block: fetch order item data for each order ---
    orderitems_map = {}
    orderitem_ids = [order.get('ORDERITEM_ID') for order in paginated_orders if order.get('ORDERITEM_ID')]
    # Remove duplicates and None
    orderitem_ids = list({oid for oid in orderitem_ids if oid is not None})
    for oid in orderitem_ids:
        orderitems_map[oid] = dbhelper.get_orderitem_by_id(oid)
    # Attach orderitem data to each order
    for order in paginated_orders:
        order['orderitem_data'] = orderitems_map.get(order.get('ORDERITEM_ID'))

    template_name = 'admin_order.html' if session['role'] == 'admin' else 'staff_order.html'
    return render_template(template_name, 
                         orders=paginated_orders, 
                         stats=stats,
                         current_page=page,
                         total_pages=total_pages,
                         total_orders=total_orders)

# ORDER DETAILS - ORDER STATUS
@app.route('/order_details/<int:order_id>')
def order_details(order_id):
    order = dbhelper.get_order_by_id(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404

    customer = dbhelper.get_customer_by_id(order['CUSTOMER_ID']) if order.get('CUSTOMER_ID') else None
    orderitem = dbhelper.get_orderitem_by_id(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else None

    detergents = dbhelper.get_orderitem_detergents(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else []
    fabcons = dbhelper.get_orderitem_fabcons(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else []

    # Calculate total price breakdown
    total_price = 0.0
    breakdown = {}
    price_per_load = get_price_per_load(order.get('ORDER_TYPE'))

    # Priority
    if orderitem and orderitem.get('PRIORITIZE_ORDER'):
        breakdown['priority'] = 50.0
        total_price += 50.0
    else:
        breakdown['priority'] = 0.0

    # Ironing
    if orderitem and orderitem.get('IRON'):
        breakdown['ironing'] = 50.0
        total_price += 50.0
    else:
        breakdown['ironing'] = 0.0

    # Folding
    if orderitem and orderitem.get('FOLD_CLOTHES'):
        breakdown['folding'] = 70.0
        total_price += 70.0
    else:
        breakdown['folding'] = 0.0

    # Total Load (₱50 per load)
    load_price = 0.0
    if order.get('TOTAL_LOAD'):
        load_price = float(order['TOTAL_LOAD']) * price_per_load
        breakdown['load'] = load_price
        total_price += load_price
    else:
        breakdown['load'] = 0.0

    # Detergents
    det_total = 0.0
    for det in detergents:
        det_total += float(det.get('total_price', 0))
    breakdown['detergents'] = det_total
    total_price += det_total

    # Fabcons
    fab_total = 0.0
    for fab in fabcons:
        fab_total += float(fab.get('total_price', 0))
    breakdown['fabcons'] = fab_total
    total_price += fab_total

    # Compose response
    return jsonify({
        'ORDER_ID': order.get('ORDER_ID'),
        'CUSTOMER_NAME': customer.get('FULLNAME') if customer else '',
        'PHONE_NUMBER': customer.get('PHONE_NUMBER') if customer else '',
        'ORDER_TYPE': order.get('ORDER_TYPE'),
        'ORDER_STATUS': order.get('ORDER_STATUS'),
        'PAYMENT_STATUS': order.get('PAYMENT_STATUS'),
        'PAYMENT_METHOD': order.get('PAYMENT_METHOD'),
        'DATE_CREATED': order.get('DATE_CREATED').strftime('%Y-%m-%d') if order.get('DATE_CREATED') else '',
        'PICKUP_SCHEDULE': order.get('PICKUP_SCHEDULE'),
        'TOTAL_LOAD': order.get('TOTAL_LOAD'),
        'TOTAL_WEIGHT': order.get('TOTAL_WEIGHT'),
        'ORDER_NOTE': order.get('ORDER_NOTE'),
        'PRIORITY': orderitem.get('PRIORITIZE_ORDER') if orderitem else False,
        'IRON': orderitem.get('IRON') if orderitem else False,
        'FOLD': orderitem.get('FOLD_CLOTHES') if orderitem else False,
        'DETERGENTS': detergents,
        'FABCONS': fabcons,
        'TOTAL_PRICE': round(total_price, 2),
        'BREAKDOWN': breakdown
    })


@app.route('/order_scan/<int:order_id>')
def order_scan(order_id):
    """Fetch order details, mark order as Pickup, and send SMS notification.

    This endpoint is intended for use by the QR scanner: when a QR is scanned
    the frontend can call this to both retrieve details and trigger pickup
    workflows (DB update + SMS forward to ESP32).
    """
    # Fetch order
    order = dbhelper.get_order_by_id(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404

    # Fetch related data
    customer = dbhelper.get_customer_by_id(order['CUSTOMER_ID']) if order.get('CUSTOMER_ID') else None
    orderitem = dbhelper.get_orderitem_by_id(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else None
    detergents = dbhelper.get_orderitem_detergents(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else []
    fabcons = dbhelper.get_orderitem_fabcons(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else []

    # Update order status to Pickup (best-effort)
    try:
        user_id = session.get('user_id')
        dbhelper.update_order_status(order_id, 'Pick-up', user_id)
        # also update local variable so response reflects change
        order['ORDER_STATUS'] = 'Pick-up'
    except Exception:
        pass

    # Build price breakdown (same logic as order_details)
    total_price = 0.0
    breakdown = {}
    if orderitem and orderitem.get('PRIORITIZE_ORDER'):
        breakdown['priority'] = 50.0
        total_price += 50.0
    else:
        breakdown['priority'] = 0.0

    if orderitem and orderitem.get('IRON'):
        breakdown['ironing'] = 50.0
        total_price += 50.0
    else:
        breakdown['ironing'] = 0.0

    if orderitem and orderitem.get('FOLD_CLOTHES'):
        breakdown['folding'] = 70.0
        total_price += 70.0
    else:
        breakdown['folding'] = 0.0

    load_price = 0.0
    if order.get('TOTAL_LOAD'):
        load_price = float(order['TOTAL_LOAD']) * 50.0
        breakdown['load'] = load_price
        total_price += load_price
    else:
        breakdown['load'] = 0.0

    det_total = 0.0
    for det in detergents:
        det_total += float(det.get('total_price', 0))
    breakdown['detergents'] = det_total
    total_price += det_total

    fab_total = 0.0
    for fab in fabcons:
        fab_total += float(fab.get('total_price', 0))
    breakdown['fabcons'] = fab_total
    total_price += fab_total

    # Try to send SMS via ESP32 forwarder (same behaviour as /api/send_sms)
    sms_status = 'not_sent'
    try:
        phone = customer.get('PHONE_NUMBER') if customer else None
        customer_name = customer.get('FULLNAME') if customer else ''
        if phone:
            message = f"Hi {customer_name or ''}, your laundry (Order #{order_id}) is now ready for pick-up. Thank you for using Laundrylink!"
            esp32_ip = os.getenv('ESP32_IP', '192.168.88.199')
            esp32_url = f"http://{esp32_ip}:8080/send_sms_gsm"
            resp = requests.post(esp32_url, json={"phone": phone, "message": message}, timeout=3)
            if resp.status_code == 200:
                sms_status = 'sent'
            else:
                sms_status = f'error_{resp.status_code}'
        else:
            sms_status = 'no_phone'
    except Exception as e:
        sms_status = f'error_exception_{str(e)}'

    # Compose response
    return jsonify({
        'ORDER_ID': order.get('ORDER_ID'),
        'CUSTOMER_NAME': customer.get('FULLNAME') if customer else '',
        'PHONE_NUMBER': customer.get('PHONE_NUMBER') if customer else '',
        'ORDER_TYPE': order.get('ORDER_TYPE'),
        'ORDER_STATUS': order.get('ORDER_STATUS'),
        'PAYMENT_STATUS': order.get('PAYMENT_STATUS'),
        'PAYMENT_METHOD': order.get('PAYMENT_METHOD'),
        'DATE_CREATED': order.get('DATE_CREATED').strftime('%Y-%m-%d') if order.get('DATE_CREATED') else '',
        'PICKUP_SCHEDULE': order.get('PICKUP_SCHEDULE'),
        'TOTAL_LOAD': order.get('TOTAL_LOAD'),
        'TOTAL_WEIGHT': order.get('TOTAL_WEIGHT'),
        'ORDER_NOTE': order.get('ORDER_NOTE'),
        'PRIORITY': orderitem.get('PRIORITIZE_ORDER') if orderitem else False,
        'IRON': orderitem.get('IRON') if orderitem else False,
        'FOLD': orderitem.get('FOLD_CLOTHES') if orderitem else False,
        'DETERGENTS': detergents,
        'FABCONS': fabcons,
        'TOTAL_PRICE': round(total_price, 2),
        'BREAKDOWN': breakdown,
        'SMS_STATUS': sms_status
    })

@app.route('/mark_order_as_paid', methods=['POST'])
def mark_order_as_paid():
    """Mark an order as paid and print the full receipt (with and without QR code)."""
    data = request.get_json()
    order_id = data.get('order_id')
    
    if not order_id:
        return jsonify({'success': False, 'error': 'Order ID is required'}), 400
    
    try:
        # Update order payment status to PAID
        order = dbhelper.get_order_by_id(order_id)
        if not order:
            return jsonify({'success': False, 'error': 'Order not found'}), 404
        
        # Get logged in user ID
        user_id = session.get('user_id')
        
        # Update the payment status to PAID
        dbhelper.update_order_payment(order_id, order.get('PAYMENT_METHOD'), 'PAID', user_id)
        
        # Get updated order details
        order = dbhelper.get_order_by_id(order_id)
        customer = dbhelper.get_customer_by_id(order['CUSTOMER_ID']) if order.get('CUSTOMER_ID') else None
        orderitem = dbhelper.get_orderitem_by_id(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else None
        detergents = dbhelper.get_orderitem_detergents(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else []
        fabcons = dbhelper.get_orderitem_fabcons(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else []
        price_per_load = get_price_per_load(order.get('ORDER_TYPE'))
        
        # Print the full receipt (twice - second one without QR)
        # Print the full receipt (twice - with QR and without QR)
        try:
            from escpos.printer import Usb
            from PIL import Image, ImageDraw, ImageFont
            import time
            
            # Add a small delay to ensure previous connection is fully closed
            time.sleep(1)
            
            p = Usb(0x0483, 0x5743, encoding='GB18030')

            # Get updated order details
            order = dbhelper.get_order_by_id(order_id)
            customer = dbhelper.get_customer_by_id(order['CUSTOMER_ID']) if order.get('CUSTOMER_ID') else None
            orderitem = dbhelper.get_orderitem_by_id(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else None
            detergents = dbhelper.get_orderitem_detergents(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else []
            fabcons = dbhelper.get_orderitem_fabcons(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else []

            # Create receipt lines
            lines = []
            lines.append("========= LAUNDRY LINK =========\n")
            lines.append(f"Order ID: {order.get('ORDER_ID')}\n")
            lines.append(f"Customer: {customer.get('FULLNAME') if customer else 'N/A'}\n")
            lines.append(f"Phone: {customer.get('PHONE_NUMBER') if customer else 'N/A'}\n")
            lines.append(f"Order Type: {order.get('ORDER_TYPE')}\n")
            lines.append(f"Status: {order.get('ORDER_STATUS')}\n")
            lines.append(f"Payment: {order.get('PAYMENT_STATUS')}\n")
            lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            lines.append("-" * 32 + "\n")
            
            # Load
            if order.get('TOTAL_LOAD'):
                lines.append(f"Loads: {order.get('TOTAL_LOAD')} x Php{price_per_load:.0f} = Php{order.get('TOTAL_LOAD') * price_per_load:.2f}\n")
            
            # Priority
            if orderitem and orderitem.get('PRIORITIZE_ORDER'):
                lines.append("Priority: Php50.00\n")
            
            # Iron
            if orderitem and orderitem.get('IRON'):
                lines.append("Ironing: Php50.00\n")
            
            # Fold
            if orderitem and orderitem.get('FOLD_CLOTHES'):
                lines.append("Folding: Php70.00\n")
            
            # Detergents
            if detergents:
                for det in detergents:
                    lines.append(f"Detergent: {det['DETERGENT_NAME']}\n")
                    lines.append(f"  Qty: {det['QUANTITY']} x Php{det['UNIT_PRICE']} = Php{det['total_price']}\n")
            else:
                lines.append("Detergent: Own\n")
            
            # Fabcons
            if fabcons:
                for fab in fabcons:
                    lines.append(f"FabCon: {fab['FABCON_NAME']}\n")
                    lines.append(f"  Qty: {fab['QUANTITY']} x Php{fab['UNIT_PRICE']} = Php{fab['total_price']}\n")
            else:
                lines.append("FabCon: Own\n")
            
            lines.append("-" * 32 + "\n")
            lines.append(f"Total Price: Php{order.get('TOTAL_PRICE'):.2f}\n")
            lines.append("\nThank you!\n")
            lines.append("================================\n")

            receipt_text = "".join(lines)
            
            # Check if order is self-service
            is_self_service = str(order.get('ORDER_TYPE', '')).lower() == 'self-service'
            
            try:
                # Print logo at top middle
                logo_path = os.path.join(app.static_folder, 'images', 'logo.jpg')
                if os.path.exists(logo_path):
                    p.image(logo_path)
                    p.text("\n")
                
                # Print header with store information
                p.set(align='center')
                p.text("LAUNDRYLINK\n")
                p.text("Sanciangko St, Cebu City, 6000\n")
                p.text("Phone: 0912-345-6789\n")
                p.text("est. 2025\n")
                p.set(align='left')
                p.text("\n")
                
                p.text(receipt_text)
                
                # SELF-SERVICE: Only print one receipt without QR code
                if is_self_service:
                    # Cut the paper after single receipt
                    p.cut()
                else:
                    # DROP-OFF: Print two receipts (first with QR, second without)
                    # Generate QR code dynamically based on order ID
                    qr_data = str(order.get('ORDER_ID', order_id))
                    qr = qrcode.QRCode(version=1, box_size=10, border=1)
                    qr.add_data(qr_data)
                    qr.make(fit=True)
                    qr_image = qr.make_image(fill_color='black', back_color='white')
                    qr_image = qr_image.convert('RGB')
                    
                    # Print dynamically generated QR code on first receipt
                    p.image(qr_image)
                    p.text("\n")

                    # Add separator between receipts
                    p.text("\n" + "=" * 32 + "\n")
                    p.text("CUT HERE - MANUAL CUT REQUIRED\n")
                    p.text("=" * 32 + "\n\n")
                    
                    # Wait for printer to finish processing first receipt
                    time.sleep(3)
                    
                    # SECOND RECEIPT WITHOUT QR CODE
                    # Print logo at top middle
                    if os.path.exists(logo_path):
                        p.image(logo_path)
                        p.text("\n")
                    
                    # Print header with store information
                    p.set(align='center')
                    p.text("LAUNDRYLINK\n")
                    p.text("Sanciangko St, Cebu City, 6000 Cebu\n")
                    p.text("Phone: 0912-345-6789\n")
                    p.text("est. 2025\n")
                    p.set(align='left')
                    p.text("\n")
                    
                    p.text(receipt_text)
                    
                    # Cut the paper after second receipt
                    p.cut()
                
                # Properly close the printer connection
                p.close()
                
            except Exception as receipt_error:
                print(f"Receipt printing error: {receipt_error}")
                # Try to close printer connection even if error occurred
                try:
                    if 'p' in locals():
                        p.close()
                except:
                    pass
                # Continue even if second receipt fails
                pass
            
        except Exception as e:
            print("Printer error:", e)
            # Try to close printer connection even if error occurred
            try:
                if 'p' in locals():
                    p.close()
            except:
                pass
        
        return jsonify({'success': True, 'message': 'Order marked as paid and receipt printed'}), 200
        
    except Exception as e:
        print("Error:", e)
        return jsonify({'success': False, 'error': str(e)}), 500

#LOGOUT
@app.route('/logout')
def logout():
    role = session.get('role')
    session.clear()
    if role == 'admin':
        return redirect(url_for('admin_login'))
    else:
        return redirect(url_for('staff_login'))

# ============== ADMIN-ONLY REPORTS =============
# ORDER REPORT 
@app.route('/admin_order_report')
def admin_order_report():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
    
    # Query parameters
    search_query = request.args.get('q', '').strip().lower()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    page = request.args.get('page', 1, type=int)
    items_per_page = 10
    
    # Default to today if no dates provided
    today = datetime.now().strftime('%Y-%m-%d')
    if not start_date and not end_date:
        start_date = today
        end_date = today
    
    # Get all orders
    all_orders = dbhelper.get_all_orders_with_priority()

    # Filter orders by search and date range (dates compared as YYYY-MM-DD strings)
    filtered_orders = []
    for order in all_orders:
        include = True
        if search_query:
            order_id_str = str(order.get('ORDER_ID', '')).lower()
            customer_name = str(order.get('CUSTOMER_NAME', '')).lower()
            if (search_query not in order_id_str) and (search_query not in customer_name):
                include = False
        if include and start_date:
            order_date_str = str(order.get('DATE_CREATED', ''))[:10]
            if not order_date_str or order_date_str < start_date:
                include = False
        if include and end_date:
            order_date_str = str(order.get('DATE_CREATED', ''))[:10]
            if not order_date_str or order_date_str > end_date:
                include = False
        if include:
            filtered_orders.append(order)

    # Show only completed AND paid orders in the report view
    filtered_orders = [
        o for o in filtered_orders
        if (o.get('ORDER_STATUS') or '').lower() == 'completed'
        and (o.get('PAYMENT_STATUS') or '').lower() == 'paid'
    ]

    # Statistics
    total_orders = len(filtered_orders)
    total_revenue = 0.0
    for o in filtered_orders:
        try:
            total_revenue += float(o.get('TOTAL_PRICE', 0) or 0)
        except Exception:
            pass

    pending_orders = [o for o in filtered_orders if (o.get('ORDER_STATUS') or '').lower() == 'pending']
    completed_orders = [o for o in filtered_orders if (o.get('ORDER_STATUS') or '').lower() == 'completed']
    
    # Basic stats for the report page (mirrors the orders view stats)
    priority_count = sum(1 for o in filtered_orders if (o.get('PRIORITY') or '').lower() == 'priority')
    normal_count = sum(1 for o in filtered_orders if (o.get('PRIORITY') or '').lower() == 'normal')
    pickup_count = sum(1 for o in filtered_orders if (o.get('ORDER_STATUS') or '').lower() == 'pickup')
    stats = {
        'priority_count': priority_count,
        'normal_count': normal_count,
        'pending_count': len(pending_orders),
        'pickup_count': pickup_count,
        'completed_count': len(completed_orders)
    }

    # Pagination
    total_pages = (total_orders + items_per_page - 1) // items_per_page if total_orders > 0 else 1
    page = max(1, min(page, total_pages)) if total_pages > 0 else 1
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    paginated_orders = filtered_orders[start_idx:end_idx]

    # Fetch order item data for each order
    orderitems_map = {}
    orderitem_ids = [order.get('ORDERITEM_ID') for order in paginated_orders if order.get('ORDERITEM_ID')]
    # Remove duplicates and None
    orderitem_ids = list({oid for oid in orderitem_ids if oid is not None})
    for oid in orderitem_ids:
        orderitem = dbhelper.get_orderitem_by_id(oid)
        if orderitem:
            # Fetch detergent details for this order item
            detergents = dbhelper.get_orderitem_detergents(oid)
            orderitem['detergents'] = detergents if detergents else []
            # Fetch fabric conditioner details for this order item
            fabcons = dbhelper.get_orderitem_fabcons(oid)
            orderitem['fabcons'] = fabcons if fabcons else []
        else:
            orderitem = {'detergents': [], 'fabcons': []}
        orderitems_map[oid] = orderitem
    
    # Attach orderitem data to each order
    for order in paginated_orders:
        oid = order.get('ORDERITEM_ID')
        if oid:
            order['orderitem_data'] = orderitems_map.get(oid)
        else:
            order['orderitem_data'] = {'detergents': [], 'fabcons': []}
    
    # BASED ON ROLE
    template_name = 'admin_order_report.html' if session['role'] == 'admin' else 'staff_order_report.html'
    return render_template(template_name, 
                         orders=paginated_orders, 
                         paginated_orders=paginated_orders,
                         page=page,
                         stats=stats,
                         current_page=page,
                         total_pages=total_pages,
                         total_orders=total_orders,
                         sales_report_df=None,  # Deprecated
                         sales_completed_orders=[],
                         sales_total_orders=0,
                         sales_total_revenue=0,
                         sales_total_cogs=0,
                         sales_total_net=0,
                         sales_view=None,
                         sales_date=None,
                         sales_month=None,
                         sales_period_label=None
    )

# INVENTORY REPORT
@app.route('/inventory_report')
def inventory_report():
    # CHECK IF ADMIN IS USER 
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
        
    # Get query parameters
    search_query = request.args.get('q', '').strip()
    inv_type = request.args.get('type', 'detergent')
    if inv_type not in ['detergent', 'fabcon']:
        inv_type = 'detergent'
    period = request.args.get('period', '')

    # Inventory Sales Report filters (period selector inside the sales section)
    inv_sales_view = request.args.get('inv_sales_view', 'daily')
    inv_sales_date = request.args.get('inv_sales_date', '')
    inv_sales_month = request.args.get('inv_sales_month', '')
    
    # Get consumed inventory data
    consumed_detergents_all = dbhelper.get_consumed_detergents_report()
    consumed_fabcons_all = dbhelper.get_consumed_fabcons_report()
    
    # Get master inventory data for low stock items
    all_detergents = dbhelper.get_all_detergents()
    all_fabric_conditioners = dbhelper.get_all_fabric_conditioners()
    
    # Helper function to convert date for sorting
    def get_sort_date(item):
        date_val = item.get('DATE_CREATED')
        if date_val is None:
            return datetime.min
        if isinstance(date_val, datetime):
            return date_val
        if isinstance(date_val, str):
            try:
                return datetime.fromisoformat(date_val)
            except:
                try:
                    return datetime.strptime(date_val, '%Y-%m-%d %H:%M:%S')
                except:
                    return datetime.min
        return datetime.min
    
    # Sort by DATE_CREATED (ascending - oldest first, newest last)
    consumed_detergents_all = sorted(consumed_detergents_all, 
                                     key=get_sort_date, 
                                     reverse=False)
    consumed_fabcons_all = sorted(consumed_fabcons_all, 
                                 key=get_sort_date, 
                                 reverse=False)
    
    # Initialize filtered data
    detergents = []
    fabric_conditioners = []
    
    # Get filtered data based on inventory type and search query
    if inv_type == 'detergent':
        if search_query:
            # Filter consumed detergents by name or ID
            search_lower = search_query.lower()
            detergents = [d for d in consumed_detergents_all 
                         if search_lower in d.get('DETERGENT_NAME', '').lower() 
                         or search_lower in str(d.get('DETERGENT_ID', ''))]
        else:
            detergents = consumed_detergents_all.copy()
        fabric_conditioners = []
    elif inv_type == 'fabcon':
        if search_query:
            # Filter consumed fabric conditioners by name or ID
            search_lower = search_query.lower()
            fabric_conditioners = [f for f in consumed_fabcons_all 
                                  if search_lower in f.get('FABCON_NAME', '').lower() 
                                  or search_lower in str(f.get('FABCON_ID', ''))]
        else:
            fabric_conditioners = consumed_fabcons_all.copy()
        detergents = []
    
    # Sort filtered data by DATE_CREATED (ascending - oldest first, newest last)
    detergents = sorted(detergents, key=get_sort_date, reverse=False)
    fabric_conditioners = sorted(fabric_conditioners, key=get_sort_date, reverse=False)
    
    # Apply period filtering if period is provided
    if period:
        from datetime import date, timedelta
        today = date.today()
        start_date_obj = None
        end_date_obj = None
        
        if period == 'daily':
            start_date_obj = datetime.combine(today, datetime.min.time())
            end_date_obj = datetime.combine(today, datetime.max.time())
        elif period == 'weekly':
            start_of_week = today - timedelta(days=today.weekday())
            start_date_obj = datetime.combine(start_of_week, datetime.min.time())
            end_date_obj = datetime.combine(today, datetime.max.time())
        elif period == 'monthly':
            start_of_month = date(today.year, today.month, 1)
            start_date_obj = datetime.combine
    
    # Get master inventory data for low stock items
    all_detergents = dbhelper.get_all_detergents()
    all_fabric_conditioners = dbhelper.get_all_fabric_conditioners()
    
    # Helper function to convert date for sorting
    def get_sort_date(item):
        date_val = item.get('DATE_CREATED')
        if date_val is None:
            return datetime.min
        if isinstance(date_val, datetime):
            return date_val
        if isinstance(date_val, str):
            try:
                return datetime.fromisoformat(date_val)
            except:
                try:
                    return datetime.strptime(date_val, '%Y-%m-%d %H:%M:%S')
                except:
                    return datetime.min
        return datetime.min
    
    # Sort by DATE_CREATED (ascending - oldest first, newest last)
    consumed_detergents_all = sorted(consumed_detergents_all, 
                                     key=get_sort_date, 
                                     reverse=False)
    consumed_fabcons_all = sorted(consumed_fabcons_all, 
                                 key=get_sort_date, 
                                 reverse=False)
    
    # Initialize filtered data
    detergents = []
    fabric_conditioners = []
    
    # Get filtered data based on inventory type and search query
    if inv_type == 'detergent':
        if search_query:
            # Filter consumed detergents by name or ID
            search_lower = search_query.lower()
            detergents = [d for d in consumed_detergents_all 
                         if search_lower in d.get('DETERGENT_NAME', '').lower() 
                         or search_lower in str(d.get('DETERGENT_ID', ''))]
        else:
            detergents = consumed_detergents_all.copy()
        fabric_conditioners = []
    elif inv_type == 'fabcon':
        if search_query:
            # Filter consumed fabric conditioners by name or ID
            search_lower = search_query.lower()
            fabric_conditioners = [f for f in consumed_fabcons_all 
                                  if search_lower in f.get('FABCON_NAME', '').lower() 
                                  or search_lower in str(f.get('FABCON_ID', ''))]
        else:
            fabric_conditioners = consumed_fabcons_all.copy()
        detergents = []
    
    # Sort filtered data by DATE_CREATED (ascending - oldest first, newest last)
    detergents = sorted(detergents, key=get_sort_date, reverse=False)
    fabric_conditioners = sorted(fabric_conditioners, key=get_sort_date, reverse=False)
    
    # Default to daily (today) if no period is provided
    if not period:
        period = 'daily'
    
    # Apply period filtering
    if period:
        from datetime import date, timedelta
        today = date.today()
        start_date_obj = None
        end_date_obj = None
        
        if period == 'daily':
            start_date_obj = datetime.combine(today, datetime.min.time())
            end_date_obj = datetime.combine(today, datetime.max.time())
        elif period == 'weekly':
            start_of_week = today - timedelta(days=today.weekday())
            start_date_obj = datetime.combine(start_of_week, datetime.min.time())
            end_date_obj = datetime.combine(today, datetime.max.time())
        elif period == 'monthly':
            start_of_month = date(today.year, today.month, 1)
            start_date_obj = datetime.combine(start_of_month, datetime.min.time())
            end_date_obj = datetime.combine(today, datetime.max.time())
        elif period == 'yearly':
            start_of_year = date(today.year, 1, 1)
            start_date_obj = datetime.combine(start_of_year, datetime.min.time())
            end_date_obj = datetime.combine(today, datetime.max.time())
        
        # Filter detergents by period
        if inv_type == 'detergent':
            filtered_detergents = []
            for item in detergents:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    try:
                        item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                    except:
                        continue
                # Remove timezone info (convert to naive) for comparison
                if item_date.tzinfo is not None:
                    item_date = item_date.replace(tzinfo=None)
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_detergents.append(item)
            detergents = filtered_detergents
        # Filter fabric conditioners by period
        elif inv_type == 'fabcon':
            filtered_fabcons = []
            for item in fabric_conditioners:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    try:
                        item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                    except:
                        continue
                # Remove timezone info (convert to naive) for comparison
                if item_date.tzinfo is not None:
                    item_date = item_date.replace(tzinfo=None)
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_fabcons.append(item)
            fabric_conditioners = filtered_fabcons
    
    # Re-sort all filtered data by DATE_CREATED (ascending - oldest first, newest last)
    detergents = sorted(detergents, key=get_sort_date, reverse=False)
    fabric_conditioners = sorted(fabric_conditioners, key=get_sort_date, reverse=False)

    # ---------------- Inventory Sales Report (Completed orders only) ----------------
    def _parse_consumed_date(value):
        """Convert stored date/timestamp to naive datetime for comparisons."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
            except Exception:
                try:
                    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
                except Exception:
                    return None
        return None

    def _is_completed(item):
        return str(item.get('ORDER_STATUS', '')).strip().lower() == 'completed'

    # Determine sales period window (defaults to today)
    today = datetime.now().date()
    inv_start_date = datetime.combine(today, datetime.min.time())
    inv_end_date = datetime.combine(today, datetime.max.time())
    inv_period_label = today.strftime('%B %d, %Y')

    if inv_sales_view == 'weekly':
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        inv_start_date = datetime.combine(start_of_week, datetime.min.time())
        inv_end_date = datetime.combine(end_of_week, datetime.max.time())
        inv_period_label = f"{start_of_week.strftime('%b %d')} - {end_of_week.strftime('%b %d, %Y')}"
    elif inv_sales_view == 'monthly':
        if inv_sales_month:
            try:
                year, month = map(int, inv_sales_month.split('-'))
            except Exception:
                year, month = today.year, today.month
        else:
            year, month = today.year, today.month
        start_of_month = datetime(year, month, 1)
        if month == 12:
            end_of_month = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_of_month = datetime(year, month + 1, 1) - timedelta(days=1)
        inv_start_date = datetime.combine(start_of_month.date(), datetime.min.time())
        inv_end_date = datetime.combine(end_of_month.date(), datetime.max.time())
        inv_period_label = start_of_month.strftime('%B %Y')
    elif inv_sales_view == 'yearly':
        start_of_year = datetime(today.year, 1, 1)
        end_of_year = datetime(today.year, 12, 31)
        inv_start_date = datetime.combine(start_of_year.date(), datetime.min.time())
        inv_end_date = datetime.combine(end_of_year.date(), datetime.max.time())
        inv_period_label = str(today.year)
    else:  # daily (default) with optional explicit date
        if inv_sales_date:
            try:
                selected_date = datetime.strptime(inv_sales_date, '%Y-%m-%d').date()
                inv_start_date = datetime.combine(selected_date, datetime.min.time())
                inv_end_date = datetime.combine(selected_date, datetime.max.time())
                inv_period_label = selected_date.strftime('%B %d, %Y')
            except Exception:
                pass

    # Build completed-only consumption lists for the sales tables
    inv_consumed_detergents = []
    inv_consumed_fabcons = []

    for d in consumed_detergents_all:
        if not _is_completed(d):
            continue
        item_date = _parse_consumed_date(d.get('DATE_CREATED'))
        if item_date and inv_start_date <= item_date <= inv_end_date:
            inv_consumed_detergents.append({
                'ITEM_ID': d.get('DETERGENT_ID'),
                'ITEM_NAME': d.get('DETERGENT_NAME'),
                'UNIT_PRICE': float(d.get('UNIT_PRICE', 0) or 0),
                'QUANTITY': int(d.get('QUANTITY', 0) or 0),
                'TOTAL_VALUE': float(d.get('TOTAL_VALUE', 0) or 0),
                'ORDER_ID': d.get('ORDER_ID')
            })

    for f in consumed_fabcons_all:
        if not _is_completed(f):
            continue
        item_date = _parse_consumed_date(f.get('DATE_CREATED'))
        if item_date and inv_start_date <= item_date <= inv_end_date:
            inv_consumed_fabcons.append({
                'ITEM_ID': f.get('FABCON_ID'),
                'ITEM_NAME': f.get('FABCON_NAME'),
                'UNIT_PRICE': float(f.get('UNIT_PRICE', 0) or 0),
                'QUANTITY': int(f.get('QUANTITY', 0) or 0),
                'TOTAL_VALUE': float(f.get('TOTAL_VALUE', 0) or 0),
                'ORDER_ID': f.get('ORDER_ID')
            })
    
    # PAGINATION LOGIC
    items_per_page = 10
    page = request.args.get('page', 1, type=int)
    if inv_type == 'detergent':
        total_items = len(detergents)
        total_pages = (total_items + items_per_page - 1) // items_per_page if total_items > 0 else 1
        if page < 1:
            page = 1
        elif page > total_pages and total_pages > 0:
            page = total_pages
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        paginated_detergents = detergents[start_idx:end_idx]
        paginated_fabcons = []
    elif inv_type == 'fabcon':
        total_items = len(fabric_conditioners)
        total_pages = (total_items + items_per_page - 1) // items_per_page if total_items > 0 else 1
        if page < 1:
            page = 1
        elif page > total_pages and total_pages > 0:
            page = total_pages
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        paginated_fabcons = fabric_conditioners[start_idx:end_idx]
        paginated_detergents = []
    else:
        paginated_detergents = detergents
        paginated_fabcons = fabric_conditioners
        total_pages = 1
        page = 1

    # Calculate inventory sales summary statistics (completed orders only)
    inv_total_detergent_qty = sum(d.get('QUANTITY', 0) for d in inv_consumed_detergents)
    inv_total_detergent_items = len(inv_consumed_detergents)
    inv_total_detergent_cost = sum(float(d.get('TOTAL_VALUE', 0) or 0) for d in inv_consumed_detergents)
    
    inv_total_fabcon_qty = sum(f.get('QUANTITY', 0) for f in inv_consumed_fabcons)
    inv_total_fabcon_items = len(inv_consumed_fabcons)
    inv_total_fabcon_cost = sum(float(f.get('TOTAL_VALUE', 0) or 0) for f in inv_consumed_fabcons)
    
    inv_total_qty = inv_total_detergent_qty + inv_total_fabcon_qty
    inv_total_cost = inv_total_detergent_cost + inv_total_fabcon_cost

    return render_template(
        'admin_inventory_report.html',
        consumed_detergents=paginated_detergents,
        consumed_fabric_conditioners=paginated_fabcons,
        all_consumed_detergents=consumed_detergents_all,
        all_consumed_fabcons=consumed_fabcons_all,
        detergents=paginated_detergents,
        fabric_conditioners=paginated_fabcons,
        all_detergents=all_detergents,
        all_fabric_conditioners=all_fabric_conditioners,
        current_page=page,
        total_pages=total_pages,
        # Inventory sales summary variables
        inv_period_label=inv_period_label,
        inv_total_detergent_qty=inv_total_detergent_qty,
        inv_total_detergent_items=inv_total_detergent_items,
        inv_total_detergent_cost=round(inv_total_detergent_cost, 2),
        inv_total_fabcon_qty=inv_total_fabcon_qty,
        inv_total_fabcon_items=inv_total_fabcon_items,
        inv_total_fabcon_cost=round(inv_total_fabcon_cost, 2),
        inv_total_qty=inv_total_qty,
        inv_total_cost=round(inv_total_cost, 2),
        # Completed-only Inventory Sales Report data
        inv_consumed_detergents=inv_consumed_detergents,
        inv_consumed_fabcons=inv_consumed_fabcons,
        inv_sales_view=inv_sales_view,
        inv_sales_date=inv_sales_date,
        inv_sales_month=inv_sales_month
    )

@app.route('/download_order_report/<format>')
def download_order_report(format):
    # Get filters from query params
    search_query = request.args.get('q', '').strip().lower()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    view = request.args.get('view', '')
    selected_month = request.args.get('month', '')
    customer_id = request.args.get('customer_id', type=int)

    # Default to today if no dates provided
    today = datetime.now().strftime('%Y-%m-%d')
    if not start_date and not end_date:
        start_date = today
        end_date = today

    # Get all orders
    orders = dbhelper.get_all_orders_with_priority()

    # If view and month are provided (from income statement page), calculate date range
    if view and not start_date and not end_date:
        now = datetime.now()
        if view == 'weekly':
            start_date_obj = now - timedelta(days=7)
            end_date_obj = now
        elif view == 'monthly':
            if selected_month:
                try:
                    year, month = map(int, selected_month.split('-'))
                    start_date_obj = datetime(year, month, 1)
                    if month == 12:
                        end_date_obj = datetime(year + 1, 1, 1) - timedelta(days=1)
                    else:
                        end_date_obj = datetime(year, month + 1, 1) - timedelta(days=1)
                    end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
                except (ValueError, AttributeError):
                    start_date_obj = now.replace(day=1)
                    end_date_obj = now
            else:
                start_date_obj = now.replace(day=1)
                end_date_obj = now
        elif view == 'yearly':
            start_date_obj = now.replace(month=1, day=1)
            end_date_obj = now
        else:
            start_date_obj = now - timedelta(days=7)
            end_date_obj = now
        
        start_date = start_date_obj.strftime('%Y-%m-%d')
        end_date = end_date_obj.strftime('%Y-%m-%d')

    # Filter orders
    filtered_orders = []
    for order in orders:
        match = True
        if search_query:
            order_id_str = str(order.get('ORDER_ID', ''))
            customer_name = str(order.get('CUSTOMER_NAME', '')).lower()
            if search_query not in order_id_str and search_query not in customer_name:
                match = False
        if start_date:
            order_date = str(order.get('DATE_CREATED', ''))[:10]
            if order_date < start_date:
                match = False
        if end_date:
            order_date = str(order.get('DATE_CREATED', ''))[:10]
            if order_date > end_date:
                match = False
        if customer_id is not None:
            if order.get('CUSTOMER_ID') != customer_id:
                match = False
        if match:
            filtered_orders.append(order)

    # For Excel/PDF exports, further restrict to completed & paid only
    if format in ['excel', 'pdf']:
        filtered_orders = [
            o for o in filtered_orders
            if (o.get('ORDER_STATUS') or '').lower() == 'completed'
            and (o.get('PAYMENT_STATUS') or '').lower() == 'paid'
        ]

    # Fetch detergent, fabric conditioner, and order item data for export
    for order in filtered_orders:
        orderitem_id = order.get('ORDERITEM_ID')
        if orderitem_id:
            orderitem = dbhelper.get_orderitem_by_id(orderitem_id)
            if orderitem:
                # Get detergent details
                detergents = dbhelper.get_orderitem_detergents(orderitem_id)
                detergent_list = []
                if detergents and len(detergents) > 0:
                    for det in detergents:
                        detergent_list.append(f"{det.get('DETERGENT_NAME')} (x{det.get('QUANTITY')})")
                    order['Detergent'] = ', '.join(detergent_list)
                elif orderitem.get('CUSTOMER_OWN_DETERGENT'):
                    order['Detergent'] = 'Own'
                else:
                    order['Detergent'] = 'N/A'
                
                # Get fabric conditioner details
                fabcons = dbhelper.get_orderitem_fabcons(orderitem_id)
                fabcon_list = []
                if fabcons and len(fabcons) > 0:
                    for fc in fabcons:
                        fabcon_list.append(f"{fc.get('FABCON_NAME')} (x{fc.get('QUANTITY')})")
                    order['Fabric Conditioner'] = ', '.join(fabcon_list)
                elif orderitem.get('CUSTOMER_OWN_FABCON'):
                    order['Fabric Conditioner'] = 'Own'
                else:
                    order['Fabric Conditioner'] = 'N/A'
                
                # Get other services
                services = []
                if orderitem.get('IRON'):
                    services.append('Iron')
                if orderitem.get('FOLD_CLOTHES'):
                    services.append('Fold')
                if orderitem.get('PRIORITIZE_ORDER'):
                    services.append('Priority')
                order['Others'] = ', '.join(services) if services else 'None'
            else:
                order['Detergent'] = 'N/A'
                order['Fabric Conditioner'] = 'N/A'
                order['Others'] = 'N/A'
        else:
            order['Detergent'] = 'N/A'
            order['Fabric Conditioner'] = 'N/A'
            order['Others'] = 'N/A'

    # Convert to DataFrame
    df = pd.DataFrame(filtered_orders)
    
    # Select and reorder columns to match table
    columns_to_keep = [
        'ORDER_ID', 'CUSTOMER_NAME', 'ORDER_TYPE', 'ORDER_STATUS', 'PAYMENT_STATUS',
        'TOTAL_PRICE', 'TOTAL_LOAD', 'TOTAL_WEIGHT', 'Detergent', 'Fabric Conditioner',
        'Others', 'PICKUP_SCHEDULE', 'DATE_CREATED', 'DATE_UPDATED'
    ]
    
    # Keep only existing columns
    available_columns = [col for col in columns_to_keep if col in df.columns]
    df = df[available_columns]
    
    # Remove any columns not in our list
    for col in ['IMAGE_FILENAME', 'QR_CODE', 'ORDERITEM_ID', 'CUSTOMER_ID', 'PHONE_NUMBER', 'PRIORITY']:
        if col in df.columns:
            df = df.drop(columns=[col])

    # Make datetimes Excel-safe
    def make_excel_safe(df):
        for col in df.columns:
            if df[col].dtype == 'datetime64[ns]' or df[col].dtype == 'datetime64[ns, UTC]':
                df[col] = df[col].dt.tz_localize(None)
            elif df[col].apply(lambda x: hasattr(x, 'tzinfo')).any():
                df[col] = df[col].apply(lambda x: x.replace(tzinfo=None) if hasattr(x, 'tzinfo') and x.tzinfo else x)
            if df[col].apply(lambda x: isinstance(x, (datetime, pd.Timestamp))).any():
                df[col] = df[col].apply(lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if isinstance(x, (datetime, pd.Timestamp)) else x)
        return df

    filename = 'order_report'
    sheet_name = 'Orders'

    # Shared totals for all formats
    total_orders = len(df)
    total_price_val = 0.0
    if 'TOTAL_PRICE' in df.columns:
        try:
            total_price_val = pd.to_numeric(df['TOTAL_PRICE'], errors='coerce').fillna(0).sum()
        except Exception:
            total_price_val = 0.0

    if format == 'excel':
        output = io.BytesIO()
        df = make_excel_safe(df)
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            # Start the table lower so the title/info sit clearly under the logo
            data_start_row = 8  # column headers; data begins at data_start_row + 1
            df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=data_start_row)

            # --- Financial-style formatting (Excel only) ---
            workbook = writer.book
            worksheet = writer.sheets[sheet_name]

            # Title/header formats
            title_fmt = workbook.add_format({
                'bold': True,
                'font_color': 'white',
                'bg_color': '#122D69',
                'align': 'center',
                'valign': 'vcenter',
                'font_size': 16,
                'border': 1
            })
            subtitle_fmt = workbook.add_format({
                'bold': True,
                'font_color': '#122D69',
                'align': 'left',
                'valign': 'vcenter',
                'font_size': 10
            })

            # Header format: bold, dark background, centered text
            header_fmt = workbook.add_format({
                'bold': True,
                'font_color': 'white',
                'bg_color': '#122D69',
                'align': 'center',
                'valign': 'vcenter',
                'border': 1
            })

            # Body formats
            center_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
            text_fmt = workbook.add_format({'align': 'left', 'valign': 'vcenter', 'text_wrap': True, 'border': 1})
            currency_fmt = workbook.add_format({
                'align': 'right',
                'valign': 'vcenter',
                'num_format': '"₱"#,##0.00',
                'border': 1
            })
            int_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'num_format': '0', 'border': 1})
            weight_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'num_format': '0.00', 'border': 1})
            total_label_fmt = workbook.add_format({'bold': True, 'align': 'right', 'valign': 'vcenter'})
            total_value_fmt = workbook.add_format({
                'bold': True,
                'align': 'right',
                'valign': 'vcenter',
                'num_format': '"₱"#,##0.00'
            })
            total_int_fmt = workbook.add_format({'bold': True, 'align': 'left', 'valign': 'vcenter'})

            # Report header (logo on top; title/info clearly beneath the logo)
            last_col = len(df.columns) - 1
            # Optional logo (if available). If missing, this is skipped silently.
            try:
                worksheet.insert_image(0, 0, 'static/images/logo.jpg', {'x_scale': 0.4, 'y_scale': 0.4})
            except Exception:
                pass
            title_row = 3
            worksheet.merge_range(title_row, 0, title_row, last_col, 'Order Report', title_fmt)
            worksheet.merge_range(title_row + 1, 0, title_row + 1, last_col, 'Laundry Link • Sanciangko St, Cebu City, 6000 Cebu', subtitle_fmt)
            worksheet.merge_range(title_row + 2, 0, title_row + 2, last_col, 'Phone: 0912-345-6789   •   est. 2025', subtitle_fmt)

            # Apply header formatting (row with column titles)
            header_row_idx = data_start_row
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(header_row_idx, col_num, value, header_fmt)

            # Suggested column widths (financial report style)
            col_widths = {
                'ORDER_ID': 10,
                'CUSTOMER_NAME': 22,
                'ORDER_TYPE': 12,
                'ORDER_STATUS': 12,
                'PAYMENT_STATUS': 14,
                'TOTAL_PRICE': 14,
                'TOTAL_LOAD': 10,
                'TOTAL_WEIGHT': 12,
                'Detergent': 24,
                'Fabric Conditioner': 24,
                'Others': 16,
                'PICKUP_SCHEDULE': 18,
                'DATE_CREATED': 18,
                'DATE_UPDATED': 18
            }

            # Apply column widths and formats
            for idx, col in enumerate(df.columns):
                width = col_widths.get(col, 14)
                if col == 'TOTAL_PRICE':
                    worksheet.set_column(idx, idx, width, currency_fmt)
                elif col == 'TOTAL_LOAD':
                    worksheet.set_column(idx, idx, width, int_fmt)
                elif col == 'TOTAL_WEIGHT':
                    worksheet.set_column(idx, idx, width, weight_fmt)
                elif col in ['ORDER_ID', 'ORDER_TYPE', 'ORDER_STATUS', 'PAYMENT_STATUS']:
                    worksheet.set_column(idx, idx, width, center_fmt)
                else:
                    worksheet.set_column(idx, idx, width, text_fmt)

            # Totals row (aligned to the right, similar to the screenshot)
            total_row_idx = data_start_row + len(df) + 2
            worksheet.write(total_row_idx, max(last_col - 4, 0), 'Total Orders:', total_label_fmt)
            worksheet.write(total_row_idx, max(last_col - 3, 1), total_orders, total_int_fmt)
            worksheet.write(total_row_idx, max(last_col - 2, 2), 'Total Price:', total_label_fmt)
            worksheet.write(total_row_idx, max(last_col - 1, 3), total_price_val, total_value_fmt)

            # Freeze header row for easier review (just below the column headers)
            worksheet.freeze_panes(data_start_row + 1, 0)

        output.seek(0)
        return send_file(output, download_name=f"{filename}.xlsx", as_attachment=True)
    elif format == 'csv':
        output = io.StringIO()
        df = make_excel_safe(df)

        # Styled CSV header to mimic the Excel report structure
        output.write("Order Report\n")
        output.write("Laundry Link • Sanciangko St, Cebu City, 6000 Cebu\n")
        output.write("Phone: 0912-345-6789 • est. 2025\n")
        output.write("\n")
        output.write(f"Total Orders: {total_orders}, Total Price: ₱{total_price_val:,.2f}\n")
        output.write("\n")

        df.to_csv(output, index=False)
        output.seek(0)
        return Response(output.getvalue(), mimetype='text/csv', headers={"Content-Disposition": f"attachment;filename={filename}.csv"})
    elif format == 'pdf':
        # Styled PDF export tuned for printing: legal (long bond) landscape
        from fpdf import FPDF

        pdf = FPDF(orientation='L', unit='mm', format='legal')
        pdf.set_left_margin(12)
        pdf.set_right_margin(12)
        pdf.set_auto_page_break(auto=True, margin=12)

        def safe_text(text):
            """Return text encoded for latin-1, replacing unsupported chars (e.g., ₱ -> PHP)."""
            if text is None:
                return ''
            cleaned = str(text).replace('₱', 'PHP')
            return cleaned.encode('latin-1', 'replace').decode('latin-1')

        def add_title_bar(title):
            """Draw a clean, thinner header bar."""
            pdf.set_fill_color(18, 45, 105)  # #122D69
            pdf.set_text_color(255, 255, 255)
            pdf.set_font('Arial', 'B', 12)
            pdf.cell(0, 9, title, ln=True, align='C', fill=True)
            pdf.ln(2)

        def estimate_lines(text, width, line_height):
            """Estimate lines needed for wrapped text at current font."""
            if text is None:
                return 1
            text = str(text)
            if not text:
                return 1
            words = text.split(' ')
            lines = 1
            current = ''
            for word in words:
                candidate = word if current == '' else f"{current} {word}"
                if pdf.get_string_width(candidate) <= (width - 2):
                    current = candidate
                else:
                    lines += 1
                    current = word
            return max(lines, 1)

        def add_table(df):
            if df.empty:
                pdf.set_text_color(200, 0, 0)
                pdf.set_font('Arial', '', 9)
                pdf.cell(0, 6, 'No data available.', ln=True, align='C')
                return

            pdf.set_fill_color(245, 247, 250)  # header background
            pdf.set_text_color(35, 56, 114)    # header text

            available_width = pdf.w - pdf.l_margin - pdf.r_margin
            columns = list(df.columns)

            # Relative weights to spread columns across full width
            weight_map = {
                'ORDER_ID': 6,
                'CUSTOMER_NAME': 12,
                'ORDER_TYPE': 7,
                'ORDER_STATUS': 7,
                'PAYMENT_STATUS': 7,
                'TOTAL_PRICE': 6,
                'TOTAL_LOAD': 4,
                'TOTAL_WEIGHT': 5,
                'Detergent': 10,
                'Fabric Conditioner': 10,
                'Others': 7,
                'PICKUP_SCHEDULE': 6,
                'DATE_CREATED': 8,
                'DATE_UPDATED': 8,
            }
            total_weight = sum(weight_map.get(col, 6) for col in columns)
            col_widths = [
                available_width * (weight_map.get(col, 6) / total_weight)
                for col in columns
            ]

            header_line_height = 4.5
            body_line_height = 5.2  # slightly reduced padding

            def render_header():
                """Render header with word-based wrapping (e.g., CUSTOMER_NAME -> CUSTOMER\nNAME)."""
                pdf.set_font('Arial', 'B', 9)
                pdf.set_fill_color(245, 247, 250)
                pdf.set_text_color(35, 56, 114)

                formatted_headers = []
                for col in columns:
                    cleaned = str(col).replace('_', ' ')
                    words = cleaned.split()
                    formatted_headers.append(safe_text('\n'.join(words) if words else cleaned))

                header_lines = [max(len(h.split('\n')), 1) for h in formatted_headers]
                header_row_height = max(header_lines) * header_line_height

                for i, text in enumerate(formatted_headers):
                    x_start = pdf.get_x()
                    y_start = pdf.get_y()
                    pdf.multi_cell(
                        col_widths[i],
                        header_line_height,
                        safe_text(text),
                        border=1,
                        align='C',
                        fill=True,
                    )
                    pdf.set_xy(x_start + col_widths[i], y_start)

                pdf.ln(header_row_height)
                # Reset body text color
                pdf.set_text_color(0, 0, 0)

            render_header()
            pdf.set_font('Arial', '', 8)

            for row_idx, row in df.iterrows():
                values = [safe_text(item) for item in row]

                max_lines = 1
                for text, width in zip(values, col_widths):
                    max_lines = max(max_lines, estimate_lines(text, width, body_line_height))

                row_height = max_lines * body_line_height

                # Ensure the row fits; if not, start a new page and redraw header
                if pdf.get_y() + row_height > pdf.page_break_trigger:
                    pdf.add_page()
                    render_header()

                # Alternate row fill
                fill_color = (248, 250, 252) if row_idx % 2 == 0 else (255, 255, 255)
                pdf.set_fill_color(*fill_color)

                y_start = pdf.get_y()
                for text, width in zip(values, col_widths):
                    x_start = pdf.get_x()
                    pdf.multi_cell(width, body_line_height, text, border=1, align='C', fill=True)
                    # Move to the next cell in the row
                    pdf.set_xy(x_start + width, y_start)
                pdf.ln(row_height)

        pdf.add_page()

        # Add logo at the top left (slightly larger) then add gap before header
        try:
            pdf.image('static/images/pdfheader.jpg', x=10, y=8, w=78)
            # Ensure there's clear vertical space between logo and header bar
            pdf.set_y(38)
        except Exception:
            pass  # Skip logo if not found

        add_title_bar('Order Report')

        # Format dataframe for display
        df_display = df.copy()

        # Format date columns
        for col in ['DATE_CREATED', 'DATE_UPDATED']:
            if col in df_display.columns:
                df_display[col] = df_display[col].apply(
                    lambda x: x.strftime('%m/%d/%Y') if isinstance(x, (datetime, pd.Timestamp)) else str(x)
                )

        add_table(df_display)

        # Footer summary: total counts and generation timestamp
        pdf.ln(4)
        pdf.set_font('Arial', 'B', 9)
        total_price_sum = 0.0
        if 'TOTAL_PRICE' in df_display.columns:
            try:
                total_price_sum = pd.to_numeric(df_display['TOTAL_PRICE'], errors='coerce').fillna(0).sum()
            except Exception:
                total_price_sum = 0.0
        total_price_display = f"PHP {total_price_sum:,.2f}"
        footer_text = safe_text(f"Total Orders: {len(df_display)}    Total Price: {total_price_display}")
        pdf.cell(0, 6, footer_text, ln=True, align='R')
        pdf.set_font('Arial', '', 8)
        generated_at = datetime.now().strftime('%B %d, %Y %I:%M %p')
        pdf.cell(0, 5, safe_text(f"Date Generated: {generated_at}"), ln=True, align='R')

        output = io.BytesIO(pdf.output(dest='S').encode('latin1'))
        output.seek(0)
        return send_file(output, download_name=f"{filename}.pdf", as_attachment=True)
    else:
        return "Invalid format", 400
     
@app.route('/download_inventory_report/<format>')
def download_inventory_report(format):
    # Check if user is admin
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
        
    # Get query parameters
    inv_type = request.args.get('type')
    search_query = request.args.get('q', '').strip()
    period = request.args.get('period', '')
    
    # Get consumed data based on inventory type
    if inv_type == 'detergent':
        if search_query:
            # Filter consumed detergents by name or ID
            search_lower = search_query.lower()
            data = [d for d in dbhelper.get_consumed_detergents_report() 
                   if search_lower in d.get('DETERGENT_NAME', '').lower() 
                   or search_lower in str(d.get('DETERGENT_ID', ''))]
        else:
            data = dbhelper.get_consumed_detergents_report()
        sheet_name = 'Consumed Detergents'
        filename = 'detergent_inventory_report'
    elif inv_type == 'fabcon':
        if search_query:
            # Filter consumed fabric conditioners by name or ID
            search_lower = search_query.lower()
            data = [f for f in dbhelper.get_consumed_fabcons_report() 
                   if search_lower in f.get('FABCON_NAME', '').lower() 
                   or search_lower in str(f.get('FABCON_ID', ''))]
        else:
            data = dbhelper.get_consumed_fabcons_report()
        sheet_name = 'Consumed Fabric Conditioners'
        filename = 'fabcon_inventory_report'
    else:
        # Get both detergent and fabric conditioner consumed data
        if search_query:
            search_lower = search_query.lower()
            det_data = [d for d in dbhelper.get_consumed_detergents_report() 
                       if search_lower in d.get('DETERGENT_NAME', '').lower() 
                       or search_lower in str(d.get('DETERGENT_ID', ''))]
            fabcon_data = [f for f in dbhelper.get_consumed_fabcons_report() 
                          if search_lower in f.get('FABCON_NAME', '').lower() 
                          or search_lower in str(f.get('FABCON_ID', ''))]
        else:
            det_data = dbhelper.get_consumed_detergents_report()
            fabcon_data = dbhelper.get_consumed_fabcons_report()
        
        filename = 'inventory_report'
    
    # Apply date filtering if dates are provided
    if period:
        from datetime import date, timedelta
        today = date.today()
        start_date_obj = None
        end_date_obj = None
        
        if period == 'daily':
            start_date_obj = datetime.combine(today, datetime.min.time())
            end_date_obj = datetime.combine(today, datetime.max.time())
        elif period == 'weekly':
            start_of_week = today - timedelta(days=today.weekday())
            start_date_obj = datetime.combine(start_of_week, datetime.min.time())
            end_date_obj = datetime.combine(today, datetime.max.time())
        elif period == 'monthly':
            start_of_month = date(today.year, today.month, 1)
            start_date_obj = datetime.combine(start_of_month, datetime.min.time())
            end_date_obj = datetime.combine(today, datetime.max.time())
        elif period == 'yearly':
            start_of_year = date(today.year, 1, 1)
            start_date_obj = datetime.combine(start_of_year, datetime.min.time())
            end_date_obj = datetime.combine(today, datetime.max.time())
        
        # Filter data by period
        if inv_type == 'detergent':
            filtered_detergents = []
            for item in data:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    try:
                        item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                    except:
                        continue
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_detergents.append(item)
            data = filtered_detergents
        elif inv_type == 'fabcon':
            filtered_fabcons = []
            for item in data:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    try:
                        item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                    except:
                        continue
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_fabcons.append(item)
            data = filtered_fabcons
        else:
            # Filter detergent data
            filtered_det_data = []
            for item in det_data:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    try:
                        item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                    except:
                        continue
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_det_data.append(item)
            det_data = filtered_det_data
            
            # Filter fabric conditioner data
            filtered_fabcon_data = []
            for item in fabcon_data:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    try:
                        item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                    except:
                        continue
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_fabcon_data.append(item)
            fabcon_data = filtered_fabcon_data
    
    # Format DATE_CREATED to mm/dd/yyyy hh:mm:ss before creating DataFrames
    def format_date_for_export(data_list):
        for item in data_list:
            if 'DATE_CREATED' in item:
                date_val = item['DATE_CREATED']
                if date_val:
                    if isinstance(date_val, datetime):
                        item['DATE_CREATED'] = date_val.strftime('%m/%d/%Y %H:%M:%S')
                    elif isinstance(date_val, str):
                        try:
                            parsed_date = datetime.strptime(date_val, '%Y-%m-%d %H:%M:%S')
                            item['DATE_CREATED'] = parsed_date.strftime('%m/%d/%Y %H:%M:%S')
                        except:
                            try:
                                parsed_date = datetime.fromisoformat(date_val)
                                item['DATE_CREATED'] = parsed_date.strftime('%m/%d/%Y %H:%M:%S')
                            except:
                                pass
        return data_list
    
    if inv_type == 'detergent':
        data = format_date_for_export(data)
    elif inv_type == 'fabcon':
        data = format_date_for_export(data)
    else:
        det_data = format_date_for_export(det_data)
        fabcon_data = format_date_for_export(fabcon_data)
    
    # Create DataFrames
    if inv_type in ['detergent', 'fabcon']:
        df = pd.DataFrame(data)
        # Add total row
        if not df.empty:
            total_value = df['TOTAL_VALUE'].astype(float).sum()
            total_row = pd.DataFrame([{
                'DETERGENT_ID' if inv_type == 'detergent' else 'FABCON_ID': 'TOTAL',
                'DETERGENT_NAME' if inv_type == 'detergent' else 'FABCON_NAME': '',
                'UNIT_PRICE': '',
                'QUANTITY': '',
                'TOTAL_VALUE': total_value,
                'DATE_CREATED': '',
                'ORDER_ID': ''
            }])
            df = pd.concat([df, total_row], ignore_index=True)
    else:
        det_df = pd.DataFrame(det_data)
        fabcon_df = pd.DataFrame(fabcon_data)
        # Add total rows
        if not det_df.empty:
            det_total_value = det_df['TOTAL_VALUE'].astype(float).sum()
            det_total_row = pd.DataFrame([{
                'DETERGENT_ID': 'TOTAL',
                'DETERGENT_NAME': '',
                'UNIT_PRICE': '',
                'QUANTITY': '',
                'TOTAL_VALUE': det_total_value,
                'DATE_CREATED': '',
                'ORDER_ID': ''
            }])
            det_df = pd.concat([det_df, det_total_row], ignore_index=True)
        if not fabcon_df.empty:
            fabcon_total_value = fabcon_df['TOTAL_VALUE'].astype(float).sum()
            fabcon_total_row = pd.DataFrame([{
                'FABCON_ID': 'TOTAL',
                'FABCON_NAME': '',
                'UNIT_PRICE': '',
                'QUANTITY': '',
                'TOTAL_VALUE': fabcon_total_value,
                'DATE_CREATED': '',
                'ORDER_ID': ''
            }])
            fabcon_df = pd.concat([fabcon_df, fabcon_total_row], ignore_index=True)

    if format == 'excel':
        output = io.BytesIO()
        def make_excel_safe(df):
            for col in df.columns:
                if df[col].dtype == 'datetime64[ns]' or df[col].dtype == 'datetime64[ns, UTC]':
                    df[col] = df[col].dt.tz_localize(None)
                # Also handle Python datetime objects
                elif df[col].apply(lambda x: hasattr(x, 'tzinfo')).any():
                    df[col] = df[col].apply(lambda x: x.replace(tzinfo=None) if hasattr(x, 'tzinfo') and x.tzinfo else x)
                # Convert all datetimes to string for Excel
                if df[col].apply(lambda x: isinstance(x, (datetime, pd.Timestamp))).any():
                    df[col] = df[col].apply(lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if isinstance(x, (datetime, pd.Timestamp)) else x)
            return df

        def break_header(text):
            if not text:
                return ''
            if '_' in text:
                return '\n'.join(text.split('_'))
            parts = text.split(' ')
            if len(text) > 14 and len(parts) > 1:
                return '\n'.join(parts)
            return text

        def apply_table_formatting(workbook, worksheet, df_for_sheet):
            header_fmt = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'align': 'center',
                'valign': 'vcenter',
                'border': 1,
                'font_size': 11
            })
            body_fmt = workbook.add_format({
                'text_wrap': True,
                'valign': 'top',
                'border': 1,
                'font_size': 10
            })
            # Rewrite headers with line breaks and apply wrap/bold
            for col_num, header in enumerate(df_for_sheet.columns):
                worksheet.write(0, col_num, header, header_fmt)
                # Auto-fit width based on header + data (capped for readability)
                col_series = df_for_sheet.iloc[:, col_num].astype(str)
                header_segments = str(header).split('\n')
                header_len = max(len(seg) for seg in header_segments)
                max_data_len = col_series.map(len).max() if not col_series.empty else 0
                # Heuristic width: keep within 12-40 chars
                width = max(header_len, max_data_len)
                width = min(max(width + 2, 12), 40)
                worksheet.set_column(col_num, col_num, width, body_fmt)
            # Add a slightly larger logo at the top-right if available
            try:
                worksheet.insert_image(0, len(df_for_sheet.columns) + 1, 'static/images/logo.jpg', {
                    'x_scale': 0.7,
                    'y_scale': 0.7
                })
            except Exception:
                pass

        if inv_type in ['detergent', 'fabcon']:
            df = make_excel_safe(df)
            df_excel = df.copy()
            df_excel.columns = [break_header(c) for c in df_excel.columns]
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_excel.to_excel(writer, sheet_name=sheet_name, index=False)
                worksheet = writer.sheets[sheet_name]
                apply_table_formatting(worksheet, df_excel)
        else:
            det_df = make_excel_safe(det_df)
            fabcon_df = make_excel_safe(fabcon_df)
            det_df_excel = det_df.copy()
            fabcon_df_excel = fabcon_df.copy()
            det_df_excel.columns = [break_header(c) for c in det_df_excel.columns]
            fabcon_df_excel.columns = [break_header(c) for c in fabcon_df_excel.columns]
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                if not det_df_excel.empty:
                    det_df_excel.to_excel(writer, sheet_name='Consumed Detergents', index=False)
                    apply_table_formatting(writer.sheets['Consumed Detergents'], det_df_excel)
                if not fabcon_df_excel.empty:
                    fabcon_df_excel.to_excel(writer, sheet_name='Consumed Fabric Conditioners', index=False)
                    apply_table_formatting(writer.sheets['Consumed Fabric Conditioners'], fabcon_df_excel)
        output.seek(0)
        return send_file(output, download_name=f"{filename}.xlsx", as_attachment=True)
    elif format == 'pdf':
        pdf = FPDF(orientation='L', unit='mm', format='legal')
        pdf.set_auto_page_break(auto=True, margin=15)

        def break_header(text):
            if not text:
                return ''
            if '_' in text:
                return '\n'.join(text.split('_'))
            parts = text.split(' ')
            if len(text) > 14 and len(parts) > 1:
                return '\n'.join(parts)
            return text

        def estimate_lines(text, width, font_size):
            pdf.set_font('Arial', '', font_size)
            if text is None or text == '':
                return 1
            text = str(text)
            # Account for explicit line breaks first
            lines = text.split('\n')
            total = 0
            for line in lines:
                words = line.split(' ')
                current = ''
                subtotal = 1
                for word in words:
                    candidate = word if current == '' else f"{current} {word}"
                    if pdf.get_string_width(candidate) <= max(width - 2, 1):
                        current = candidate
                    else:
                        subtotal += 1
                        current = word
                total += subtotal
            return max(total, 1)

        def add_title_bar(title):
            pdf.set_fill_color(18, 45, 105)  # #122D69
            pdf.set_text_color(255, 255, 255)
            pdf.set_font('Arial', 'B', 16)
            pdf.cell(0, 14, title, ln=True, align='C', fill=True)
            pdf.ln(3)

        def add_table(df):
            if df.empty:
                pdf.set_text_color(200, 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 7, 'No data available.', ln=True, align='C')
                return

            # Prepare columns and widths
            available_width = pdf.w - 2 * pdf.l_margin
            columns = [break_header(c) for c in df.columns]
            col_widths = []
            for col in df.columns:
                if 'NAME' in col or 'Value' in col:
                    col_widths.append(available_width * 0.18)
                elif 'ID' in col or 'ORDER' in col:
                    col_widths.append(available_width * 0.10)
                elif 'DATE' in col:
                    col_widths.append(available_width * 0.18)
                else:
                    col_widths.append(available_width * 0.12)
            total_width = sum(col_widths)
            if total_width > 0:
                col_widths = [w * available_width / total_width for w in col_widths]

            header_line_height = 5
            body_line_height = 4.5

            def render_header():
                pdf.set_font('Arial', 'B', 9)
                pdf.set_fill_color(245, 247, 250)
                pdf.set_text_color(35, 56, 114)
                # Determine header height
                max_header_lines = 1
                for header, width in zip(columns, col_widths):
                    max_header_lines = max(max_header_lines, estimate_lines(header, width, 9))
                header_height = max_header_lines * header_line_height
                y_start = pdf.get_y()
                for header, width in zip(columns, col_widths):
                    x_start = pdf.get_x()
                    pdf.multi_cell(width, header_line_height, header, border=1, align='C', fill=True)
                    pdf.set_xy(x_start + width, y_start)
                pdf.ln(header_height)
                pdf.set_text_color(0, 0, 0)

            render_header()
            pdf.set_font('Arial', '', 8)
            for row_idx, row in df.iterrows():
                # Alternate row fill
                pdf.set_fill_color(248, 250, 252) if row_idx % 2 == 0 else pdf.set_fill_color(255, 255, 255)
                # Calculate row height
                max_lines = 1
                for val, width in zip(row, col_widths):
                    max_lines = max(max_lines, estimate_lines(val, width, 8))
                row_height = max_lines * body_line_height
                # Page break check
                if pdf.get_y() + row_height > pdf.page_break_trigger:
                    pdf.add_page()
                    render_header()
                y_start = pdf.get_y()
                for val, width in zip(row, col_widths):
                    x_start = pdf.get_x()
                    pdf.multi_cell(width, body_line_height, str(val), border=1, align='C', fill=True)
                    pdf.set_xy(x_start + width, y_start)
                pdf.ln(row_height)

        def add_logo():
            try:
                # Place logo at top-left and move cursor below it so header bar sits under the logo
                pdf.image('static/images/pdfheader.jpg', x=10, y=8, w=78)
                pdf.set_y(40)  # tighten gap between logo and header
            except Exception:
                pass

        if inv_type == 'detergent':
            pdf.add_page()
            add_logo()
            add_title_bar('Consumed Detergent Report')
            add_table(df)
        elif inv_type == 'fabcon':
            pdf.add_page()
            add_logo()
            add_title_bar('Consumed Fabric Conditioner Report')
            add_table(df)
        else:
            pdf.add_page()
            add_logo()
            add_title_bar('Consumed Detergent Report')
            add_table(det_df)
            pdf.add_page()
            add_logo()
            add_title_bar('Consumed Fabric Conditioner Report')
            add_table(fabcon_df)
        output = io.BytesIO(pdf.output(dest='S').encode('latin1'))
        output.seek(0)
        return send_file(output, download_name=f"{filename}.pdf", as_attachment=True)
    elif format == 'csv':
        output = io.StringIO()
        if inv_type in ['detergent', 'fabcon']:
            df.to_csv(output, index=False)
            output.seek(0)
            return send_file(io.BytesIO(output.getvalue().encode()), download_name=f"{filename}.csv", as_attachment=True, mimetype='text/csv')
        else:
            # If both, zip two CSVs
            import zipfile
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w') as zf:
                det_csv = det_df.to_csv(index=False)
                fabcon_csv = fabcon_df.to_csv(index=False)
                zf.writestr('detergents.csv', det_csv)
                zf.writestr('fabric_conditioners.csv', fabcon_csv)
            zip_buffer.seek(0)
            return send_file(zip_buffer, download_name=f"{filename}.zip", as_attachment=True, mimetype='application/zip')
    else:
        return "Invalid format", 400

@app.route('/customer_report')
def customer_report():
    # Check if admin is logged in
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
    
    search_query = request.args.get('q', '').strip()
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    file_format = request.args.get('format')
    customer_type = request.args.get('type', 'all')
    
    # Default to today if no dates provided
    today = datetime.now().strftime('%Y-%m-%d')
    if not date_from and not date_to:
        date_from = today
        date_to = today
    
    if file_format:
        return redirect(url_for('download_customer_report', format=file_format, 
                                type=customer_type, q=search_query, 
                                date_from=date_from, date_to=date_to))
    
    # Get all customers with stats (batch)
    customers = dbhelper.get_all_customers_with_order_stats()
    
    if search_query:
        customers = [c for c in customers if search_query.lower() in c['FULLNAME'].lower() or 
                     search_query in str(c['CUSTOMER_ID']) or 
                     (c['PHONE_NUMBER'] and search_query in c['PHONE_NUMBER'])]
    
    # Define helper function to normalize datetimes
    def make_naive(dt):
        if dt is None:
            return None
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    
    # Apply date filtering
    if date_from or date_to:
        filtered_customers = []
        for customer in customers:
            include = True
            if date_from and customer['DATE_CREATED']:
                from_date = datetime.strptime(date_from, '%Y-%m-%d')
                if make_naive(customer['DATE_CREATED']) < from_date:
                    include = False
            if date_to and customer['DATE_CREATED']:
                to_date = datetime.strptime(date_to, '%Y-%m-%d')
                to_date = to_date.replace(hour=23, minute=59, second=59)
                if make_naive(customer['DATE_CREATED']) > to_date:
                    include = False
            if include:
                filtered_customers.append(customer)
        customers = filtered_customers
    
    # Show only customers whose latest order is both Completed and Paid
    def _is_completed_paid(cust):
        status = str(cust.get('ORDER_STATUS', '')).strip().lower()
        payment = str(cust.get('PAYMENT_STATUS', '')).strip().lower()
        return status == 'completed' and payment == 'paid'
    customers = [c for c in customers if _is_completed_paid(c)]
    total_customers = len(customers)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    new_customers_list = [
        c for c in customers
        if c['DATE_CREATED'] and make_naive(c['DATE_CREATED']) >= make_naive(thirty_days_ago)
    ]
    
    # Get daily customer counts and find the highest count for today/latest day
    daily_counts = dbhelper.get_daily_customer_counts()
    highest_daily_count = max(daily_counts.values()) if daily_counts else 0
    
    total_orders = sum(c.get('total_orders', 0) for c in customers)
    # avg_orders = round(total_orders / total_customers, 2) if total_customers > 0 else 0
    # Get monthly growth from dbhelper
    stats = dbhelper.get_customer_statistics()
    monthly_growth = stats.get('monthly_growth', 0)

    # PAGINATION LOGIC
    page = request.args.get('page', 1, type=int)
    per_page = 10
    total_items = len(customers)
    total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1
    page = max(1, min(page, total_pages)) if total_pages > 0 else 1
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_customers = customers[start_idx:end_idx]

    return render_template('admin_customer_report.html', 
                          transactions=paginated_customers,
                          total_customers=total_customers,
                          new_customers_count=highest_daily_count,
                          total_orders=total_orders,
                          customer_monthly_growth=monthly_growth,  # <-- changed variable name
                          current_page=page,
                          total_pages=total_pages,
                          daily_customer_counts=daily_counts)

@app.route('/download_customer_report/<format>')
def download_customer_report(format):
    # Check if user is admin
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
        
    customer_type = request.args.get('type', 'all')
    search_query = request.args.get('q', '').strip()
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    # Default to today if no dates provided
    today = datetime.now().strftime('%Y-%m-%d')
    if not date_from and not date_to:
        date_from = today
        date_to = today
    
    # Get all customers with stats (batch)
    customers = dbhelper.get_all_customers_with_order_stats()
    
    # Apply search filter
    if search_query:
        customers = [c for c in customers if search_query.lower() in c['FULLNAME'].lower() or 
                     search_query in str(c['CUSTOMER_ID']) or 
                     (c['PHONE_NUMBER'] and search_query in c['PHONE_NUMBER'])]
    
    # Define helper function to normalize datetimes
    def make_naive(dt):
        if dt is None:
            return None
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    
    # Apply date filtering
    if date_from or date_to:
        filtered_customers = []
        for customer in customers:
            include = True
            if date_from and customer['DATE_CREATED']:
                from_date = datetime.strptime(date_from, '%Y-%m-%d')
                if make_naive(customer['DATE_CREATED']) < from_date:
                    include = False
            if date_to and customer['DATE_CREATED']:
                to_date = datetime.strptime(date_to, '%Y-%m-%d')
                to_date = to_date.replace(hour=23, minute=59, second=59)
                if make_naive(customer['DATE_CREATED']) > to_date:
                    include = False
            if include:
                filtered_customers.append(customer)
        customers = filtered_customers
    thirty_days_ago = datetime.now() - timedelta(days=30)
    new_customers_list = [
        c for c in customers
        if c['DATE_CREATED'] and make_naive(c['DATE_CREATED']) >= make_naive(thirty_days_ago)
    ]
    if customer_type == 'new':
        customers_to_display = new_customers_list
        filename = 'new_customer_report'
        sheet_name = 'New Customers'
    else:
        customers_to_display = customers
        filename = 'all_customer_report'
        sheet_name = 'All Customers'
    
    if format == 'excel':
        output = io.BytesIO()
        
        # Create DataFrame
        data = []
        total_revenue = 0.0
        for customer in customers_to_display:
            total_price = float(customer.get('TOTAL_PRICE', 0) or 0)
            total_revenue += total_price
            data.append({
                'Customer ID': customer['CUSTOMER_ID'],
                'Customer Name': customer['FULLNAME'],
                'Phone Number': customer['PHONE_NUMBER'] or 'N/A',
                'Order ID': customer.get('ORDER_ID', 'N/A'),
                'Order Type': customer.get('ORDER_TYPE', 'N/A'),
                'Order Status': customer.get('ORDER_STATUS', 'N/A'),
                'Payment Status': customer.get('PAYMENT_STATUS', 'N/A'),
                'Total Price': total_price,
                'Date Created': customer['DATE_CREATED'].strftime('%Y-%m-%d') if customer['DATE_CREATED'] else 'N/A',
                'Date Updated': customer.get('DATE_UPDATED').strftime('%Y-%m-%d') if customer.get('DATE_UPDATED') else 'N/A'
            })
        
        df = pd.DataFrame(data)
        
        # Add total row
        if not df.empty:
            total_row = pd.DataFrame([{
                'Customer ID': 'TOTAL',
                'Customer Name': '',
                'Phone Number': '',
                'Order ID': '',
                'Order Type': '',
                'Order Status': '',
                'Payment Status': '',
                'Total Price': total_revenue,
                'Date Created': '',
                'Date Updated': ''
            }])
            df = pd.concat([df, total_row], ignore_index=True)
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            workbook = writer.book
            worksheet = writer.sheets[sheet_name]
            
            # Add a header format
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'fg_color': '#122D69',
                'font_color': 'white',
                'border': 1
            })
            
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)
                
            worksheet.set_column('A:A', 8)   # ID
            worksheet.set_column('B:B', 20)  # Customer Name
            worksheet.set_column('C:C', 15)  # Phone Number
            worksheet.set_column('D:D', 12)  # Order ID
            worksheet.set_column('E:E', 15)  # Order Type
            worksheet.set_column('F:F', 15)  # Order Status
            worksheet.set_column('G:G', 15)  # Payment Status
            worksheet.set_column('H:H', 12)  # Total Price
            worksheet.set_column('I:I', 15)  # Date Created
            worksheet.set_column('J:J', 15)  # Date Updated
            
            # Format the total row (last row)
            total_fmt = workbook.add_format({
                'bold': True,
                'align': 'right',
                'valign': 'vcenter',
                'num_format': '0.00',
                'bg_color': '#f5f7fa',
                'border': 1
            })
            last_row = len(df)
            worksheet.write(last_row, 7, total_revenue, total_fmt)
            
        output.seek(0)
        return send_file(output, download_name=f"{filename}.xlsx", as_attachment=True)
    
    elif format == 'pdf':
        pdf = FPDF(orientation='L', unit='mm', format='legal')
        pdf.set_auto_page_break(auto=True, margin=8)
        
        def add_title_bar(title):
            pdf.set_fill_color(18, 45, 105)  # #122D69
            pdf.set_text_color(255, 255, 255)
            pdf.set_font('Arial', 'B', 14)
            pdf.cell(0, 10, title, ln=True, align='C', fill=True)
            pdf.ln(1)

        def add_table(df):
            if df.empty:
                pdf.set_text_color(200, 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 7, 'No data available.', ln=True, align='C')
                return
                
            pdf.set_font('Arial', 'B', 6)
            pdf.set_fill_color(245, 247, 250)  # #f5f7fa
            pdf.set_text_color(35, 56, 114)    # #233872
            
            available_width = pdf.w - 2 * pdf.l_margin
            columns = ['Cust ID', 'Customer Name', 'Phone', 'Order ID', 'Order Type', 'Status', 'Payment', 'Total Price', 'Date Created', 'Date Updated']
            
            col_widths = [
                available_width * 0.07,  # Cust ID
                available_width * 0.14,  # Customer Name
                available_width * 0.10,  # Phone
                available_width * 0.08,  # Order ID
                available_width * 0.10,  # Order Type
                available_width * 0.09,  # Status
                available_width * 0.09,  # Payment
                available_width * 0.09,  # Total Price
                available_width * 0.09,  # Date Created
                available_width * 0.09   # Date Updated
            ]
            
            # Header
            for i, col in enumerate(columns):
                pdf.cell(col_widths[i], 5, str(col), border=1, align='C', fill=True)
            pdf.ln()
            
            pdf.set_font('Arial', '', 6)
            for row_idx, customer in df.iterrows():
                if row_idx % 2 == 0:
                    pdf.set_fill_color(248, 250, 252)  # #f8fafc
                else:
                    pdf.set_fill_color(255, 255, 255)  # white
                pdf.set_text_color(0, 0, 0)
                
                pdf.cell(col_widths[0], 5, str(customer.get('Customer ID', 'N/A')), border=1, align='C', fill=True)
                pdf.cell(col_widths[1], 5, str(customer.get('Customer Name', 'N/A'))[:20], border=1, align='L', fill=True)
                pdf.cell(col_widths[2], 5, str(customer.get('Phone Number', 'N/A'))[:12], border=1, align='C', fill=True)
                pdf.cell(col_widths[3], 5, str(customer.get('Order ID', 'N/A')), border=1, align='C', fill=True)
                pdf.cell(col_widths[4], 5, str(customer.get('Order Type', 'N/A'))[:10], border=1, align='C', fill=True)
                pdf.cell(col_widths[5], 5, str(customer.get('Order Status', 'N/A'))[:10], border=1, align='C', fill=True)
                pdf.cell(col_widths[6], 5, str(customer.get('Payment Status', 'N/A'))[:10], border=1, align='C', fill=True)
                pdf.cell(col_widths[7], 5, f"P {float(customer.get('Total Price', 0) or 0):.2f}", border=1, align='R', fill=True)
                pdf.cell(col_widths[8], 5, str(customer.get('Date Created', 'N/A')), border=1, align='C', fill=True)
                pdf.cell(col_widths[9], 5, str(customer.get('Date Updated', 'N/A')), border=1, align='C', fill=True)
                pdf.ln()

        # Create DataFrame
        data = []
        total_revenue = 0.0
        for customer in customers_to_display:
            total_price = float(customer.get('TOTAL_PRICE', 0) or 0)
            total_revenue += total_price
            data.append({
                'Customer ID': customer['CUSTOMER_ID'],
                'Customer Name': customer['FULLNAME'],
                'Phone Number': customer['PHONE_NUMBER'] or 'N/A',
                'Order ID': customer.get('ORDER_ID', 'N/A'),
                'Order Type': customer.get('ORDER_TYPE', 'N/A'),
                'Order Status': customer.get('ORDER_STATUS', 'N/A'),
                'Payment Status': customer.get('PAYMENT_STATUS', 'N/A'),
                'Total Price': total_price,
                'Date Created': customer['DATE_CREATED'].strftime('%Y-%m-%d') if customer['DATE_CREATED'] else 'N/A',
                'Date Updated': customer.get('DATE_UPDATED').strftime('%Y-%m-%d') if customer.get('DATE_UPDATED') else 'N/A'
            })
        df = pd.DataFrame(data)
        
        pdf.add_page()
        
        # Add logo at the top left
        try:
            pdf.image('static/images/pdfheader.jpg', x=10, y=10, w=50)
            pdf.ln(20)  # Move down after logo
        except:
            pass  # Skip logo if not found
        
        add_title_bar(f"{sheet_name} Report")
        
        if date_from or date_to:
            pdf.set_font('Arial', '', 8)
            pdf.set_text_color(0, 0, 0)
            date_range = "Date Range: "
            if date_from:
                date_range += f"From {date_from} "
            if date_to:
                date_range += f"To {date_to}"
            pdf.cell(0, 5, date_range, ln=True, align='L')
            pdf.ln(1)
        
        add_table(df)
        
        # Footer summary: total count and total revenue
        pdf.ln(3)
        pdf.set_font('Arial', 'B', 8)
        total_revenue_display = f"PHP {total_revenue:,.2f}"
        footer_text = f"Total Transactions: {len(df)}    Total Revenue: {total_revenue_display}"
        pdf.cell(0, 5, footer_text, ln=True, align='R')
        pdf.set_font('Arial', '', 7)
        generated_at = datetime.now().strftime('%B %d, %Y %I:%M %p')
        pdf.cell(0, 4, f"Date Generated: {generated_at}", ln=True, align='R')
        
        output = io.BytesIO(pdf.output(dest='S').encode('latin1'))
        output.seek(0)
        return send_file(output, download_name=f"{filename}.pdf", as_attachment=True)
    
    elif format == 'csv':
        output = io.StringIO()
        
        data = []
        for customer in customers_to_display:
            data.append({
                'Customer ID': customer['CUSTOMER_ID'],
                'Customer Name': customer['FULLNAME'],
                'Phone Number': customer['PHONE_NUMBER'] or 'N/A',
                'Order ID': customer.get('ORDER_ID', 'N/A'),
                'Order Type': customer.get('ORDER_TYPE', 'N/A'),
                'Order Status': customer.get('ORDER_STATUS', 'N/A'),
                'Payment Status': customer.get('PAYMENT_STATUS', 'N/A'),
                'Total Price': float(customer.get('TOTAL_PRICE', 0) or 0),
                'Date Created': customer['DATE_CREATED'].strftime('%Y-%m-%d') if customer['DATE_CREATED'] else 'N/A',
                'Date Updated': customer.get('DATE_UPDATED').strftime('%Y-%m-%d') if customer.get('DATE_UPDATED') else 'N/A'
            })
        
        df = pd.DataFrame(data)
        df.to_csv(output, index=False)
        
        response_data = output.getvalue()
        output.close()
        
        return Response(
            response_data,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename={filename}.csv"}
        )
    else:
        return "Invalid format", 400

@app.route('/download_inventory_sales_report/<format>')
def download_inventory_sales_report(format):
    """Download inventory consumption report (consumed detergents and fabric conditioners) as Excel, CSV, or PDF."""
    # Check if user is admin
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
    
    from datetime import date, timedelta
    
    # Get filter parameters
    inv_sales_view = request.args.get('inv_sales_view', 'daily')
    inv_sales_date = request.args.get('inv_sales_date', '')
    inv_sales_month = request.args.get('inv_sales_month', '')
    
    # Determine date range based on view
    today = date.today()
    if inv_sales_view == 'daily':
        if inv_sales_date:
            try:
                selected_date = datetime.strptime(inv_sales_date, '%Y-%m-%d').date()
            except:
                selected_date = today
        else:
            selected_date = today
        inv_start_date = datetime.combine(selected_date, datetime.min.time())
        inv_end_date = datetime.combine(selected_date, datetime.max.time())
        inv_period_label = selected_date.strftime('%B %d, %Y')
    elif inv_sales_view == 'weekly':
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        inv_start_date = datetime.combine(start_of_week, datetime.min.time())
        inv_end_date = datetime.combine(end_of_week, datetime.max.time())
        inv_period_label = f"{start_of_week.strftime('%b %d')} - {end_of_week.strftime('%b %d, %Y')}"
    elif inv_sales_view == 'monthly':
        if inv_sales_month:
            try:
                year, month = map(int, inv_sales_month.split('-'))
            except:
                year, month = today.year, today.month
        else:
            year, month = today.year, today.month
        start_of_month = date(year, month, 1)
        if month == 12:
            end_of_month = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_of_month = date(year, month + 1, 1) - timedelta(days=1)
        inv_start_date = datetime.combine(start_of_month, datetime.min.time())
        inv_end_date = datetime.combine(end_of_month, datetime.max.time())
        inv_period_label = start_of_month.strftime('%B %Y')
    elif inv_sales_view == 'yearly':
        start_of_year = date(today.year, 1, 1)
        end_of_year = date(today.year, 12, 31)
        inv_start_date = datetime.combine(start_of_year, datetime.min.time())
        inv_end_date = datetime.combine(end_of_year, datetime.max.time())
        inv_period_label = str(today.year)
    else:
        inv_start_date = datetime.combine(today, datetime.min.time())
        inv_end_date = datetime.combine(today, datetime.max.time())
        inv_period_label = today.strftime('%B %d, %Y')
    
    # Get consumed inventory data
    consumed_detergents_all = dbhelper.get_consumed_detergents_report()
    consumed_fabcons_all = dbhelper.get_consumed_fabcons_report()
    
    # Helper function to parse dates
    def parse_consumed_date(item):
        date_val = item.get('DATE_CREATED')
        if date_val is None:
            return None
        if isinstance(date_val, datetime):
            if date_val.tzinfo is not None:
                return date_val.replace(tzinfo=None)
            return date_val
        if isinstance(date_val, str):
            try:
                parsed = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
                if parsed.tzinfo is not None:
                    return parsed.replace(tzinfo=None)
                return parsed
            except:
                try:
                    return datetime.strptime(date_val, '%Y-%m-%d %H:%M:%S')
                except:
                    return None
        return None
    
    # Filter consumed detergents within date range
    inv_consumed_detergents = []
    for d in consumed_detergents_all:
        if str(d.get('ORDER_STATUS', '')).strip().lower() != 'completed':
            continue
        item_date = parse_consumed_date(d)
        if item_date and inv_start_date <= item_date <= inv_end_date:
            inv_consumed_detergents.append({
                'Item ID': d.get('DETERGENT_ID'),
                'Item Name': d.get('DETERGENT_NAME'),
                'Type': 'Detergent',
                'Unit Price': float(d.get('UNIT_PRICE', 0)),
                'Quantity': int(d.get('QUANTITY', 0)),
                'Total Cost': float(d.get('TOTAL_VALUE', 0)),
                'Order ID': d.get('ORDER_ID')
            })
    
    # Filter consumed fabric conditioners within date range
    inv_consumed_fabcons = []
    for f in consumed_fabcons_all:
        if str(f.get('ORDER_STATUS', '')).strip().lower() != 'completed':
            continue
        item_date = parse_consumed_date(f)
        if item_date and inv_start_date <= item_date <= inv_end_date:
            inv_consumed_fabcons.append({
                'Item ID': f.get('FABCON_ID'),
                'Item Name': f.get('FABCON_NAME'),
                'Type': 'Fabric Conditioner',
                'Unit Price': float(f.get('UNIT_PRICE', 0)),
                'Quantity': int(f.get('QUANTITY', 0)),
                'Total Cost': float(f.get('TOTAL_VALUE', 0)),
                'Order ID': f.get('ORDER_ID')
            })
    
    # Calculate totals
    inv_total_detergent_qty = sum(d['Quantity'] for d in inv_consumed_detergents)
    inv_total_detergent_cost = sum(d['Total Cost'] for d in inv_consumed_detergents)
    inv_total_fabcon_qty = sum(f['Quantity'] for f in inv_consumed_fabcons)
    inv_total_fabcon_cost = sum(f['Total Cost'] for f in inv_consumed_fabcons)
    inv_total_qty = inv_total_detergent_qty + inv_total_fabcon_qty
    inv_total_cost = inv_total_detergent_cost + inv_total_fabcon_cost
    
    # Create DataFrames
    det_df = pd.DataFrame(inv_consumed_detergents)
    fabcon_df = pd.DataFrame(inv_consumed_fabcons)
    
    # Add total rows
    if not det_df.empty:
        det_total_row = pd.DataFrame([{
            'Item ID': 'SUBTOTAL',
            'Item Name': '',
            'Type': '',
            'Unit Price': '',
            'Quantity': inv_total_detergent_qty,
            'Total Cost': inv_total_detergent_cost,
            'Order ID': ''
        }])
        det_df = pd.concat([det_df, det_total_row], ignore_index=True)
    
    if not fabcon_df.empty:
        fabcon_total_row = pd.DataFrame([{
            'Item ID': 'SUBTOTAL',
            'Item Name': '',
            'Type': '',
            'Unit Price': '',
            'Quantity': inv_total_fabcon_qty,
            'Total Cost': inv_total_fabcon_cost,
            'Order ID': ''
        }])
        fabcon_df = pd.concat([fabcon_df, fabcon_total_row], ignore_index=True)
    
    filename = f'inventory_consumption_report_{inv_sales_view}'
    
    if format == 'excel':
        def break_header(text):
            if not text:
                return ''
            if '_' in text:
                return '\n'.join(text.split('_'))
            parts = text.split(' ')
            if len(text) > 14 and len(parts) > 1:
                return '\n'.join(parts)
            return text

        def apply_table_formatting(workbook, worksheet, df_for_sheet, table_start_row, title_text):
            """Apply clean, professional formatting with logo/header to a worksheet."""
            header_fmt = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'align': 'center',
                'valign': 'vcenter',
                'border': 1,
                'font_size': 11,
                'bg_color': '#122D69',
                'font_color': 'white'
            })
            text_fmt = workbook.add_format({
                'text_wrap': True,
                'valign': 'top',
                'align': 'center',
                'border': 1,
                'font_size': 10
            })
            int_fmt = workbook.add_format({
                'valign': 'top',
                'align': 'center',
                'border': 1,
                'font_size': 10,
                'num_format': '0'
            })
            currency_fmt = workbook.add_format({
                'valign': 'top',
                'border': 1,
                'font_size': 10,
                'align': 'right',
                'num_format': '"₱"#,##0.00'
            })

            title_fmt = workbook.add_format({
                'bold': True,
                'font_color': 'white',
                'bg_color': '#122D69',
                'align': 'center',
                'valign': 'vcenter',
                'font_size': 16,
                'border': 1
            })
            subtitle_fmt = workbook.add_format({
                'bold': True,
                'font_color': '#122D69',
                'align': 'left',
                'valign': 'vcenter',
                'font_size': 10
            })

            last_col = len(df_for_sheet.columns) - 1

            # Logo
            try:
                worksheet.insert_image(0, 0, 'static/images/logo.jpg', {'x_scale': 0.4, 'y_scale': 0.4})
            except Exception:
                pass

            # Header texts
            title_row = 3
            if last_col >= 0:
                worksheet.merge_range(title_row, 0, title_row, last_col, title_text, title_fmt)
                worksheet.merge_range(title_row + 1, 0, title_row + 1, last_col, 'Laundry Link • Sanciangko St, Cebu City, 6000 Cebu', subtitle_fmt)
                worksheet.merge_range(title_row + 2, 0, title_row + 2, last_col, 'Phone: 0912-345-6789   •   est. 2025', subtitle_fmt)

            # Rewrite headers with header style
            for col_num, header in enumerate(df_for_sheet.columns):
                worksheet.write(table_start_row, col_num, header, header_fmt)

            # Suggested widths and per-column formats
            width_map = {
                'Item ID': 12,
                'Item Name': 26,
                'Type': 14,
                'Unit Price': 14,
                'Quantity': 10,
                'Total Cost': 16,
                'Order ID': 12,
                'Category': 18,
                'Items Consumed': 16,
            }
            for idx, col in enumerate(df_for_sheet.columns):
                width = width_map.get(col, 14)
                col_fmt = text_fmt
                if col in ['Unit Price', 'Total Cost']:
                    col_fmt = currency_fmt
                elif col in ['Quantity', 'Items Consumed']:
                    col_fmt = int_fmt
                worksheet.set_column(idx, idx, width, col_fmt)

            # Freeze header row
            worksheet.freeze_panes(table_start_row + 1, 0)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            workbook = writer.book
            table_start_row = 8

            # Write detergents sheet
            if not det_df.empty:
                det_df_excel = det_df.copy()
                det_df_excel.columns = [break_header(c) for c in det_df_excel.columns]
                det_df_excel.to_excel(writer, sheet_name='Consumed Detergents', index=False, startrow=table_start_row + 1, header=False)
                apply_table_formatting(workbook, writer.sheets['Consumed Detergents'], det_df_excel, table_start_row, 'Inventory Consumption Report')
            
            # Write fabric conditioners sheet
            if not fabcon_df.empty:
                fabcon_df_excel = fabcon_df.copy()
                fabcon_df_excel.columns = [break_header(c) for c in fabcon_df_excel.columns]
                fabcon_df_excel.to_excel(writer, sheet_name='Consumed Fabric Conditioners', index=False, startrow=table_start_row + 1, header=False)
                apply_table_formatting(workbook, writer.sheets['Consumed Fabric Conditioners'], fabcon_df_excel, table_start_row, 'Inventory Consumption Report')
            
            # Write summary sheet
            summary_data = [
                {'Category': 'Detergents', 'Items Consumed': inv_total_detergent_qty, 'Total Cost': inv_total_detergent_cost},
                {'Category': 'Fabric Conditioners', 'Items Consumed': inv_total_fabcon_qty, 'Total Cost': inv_total_fabcon_cost},
                {'Category': 'TOTAL', 'Items Consumed': inv_total_qty, 'Total Cost': inv_total_cost}
            ]
            summary_df = pd.DataFrame(summary_data)
            summary_df_excel = summary_df.copy()
            summary_df_excel.columns = [break_header(c) for c in summary_df_excel.columns]
            summary_df_excel.to_excel(writer, sheet_name=f'Summary ({inv_period_label})', index=False, startrow=table_start_row + 1, header=False)
            apply_table_formatting(workbook, writer.sheets[f'Summary ({inv_period_label})'], summary_df_excel, table_start_row, f'Inventory Consumption Summary ({inv_period_label})')
        
        output.seek(0)
        return send_file(output, download_name=f"{filename}.xlsx", as_attachment=True)
    
    elif format == 'csv':
        # Combine both into one CSV with a separator
        output = io.StringIO()
        output.write(f"Inventory Consumption Report - {inv_period_label}\n\n")
        output.write("=== CONSUMED DETERGENTS ===\n")
        if not det_df.empty:
            det_df.to_csv(output, index=False)
        else:
            output.write("No detergents consumed\n")
        output.write("\n=== CONSUMED FABRIC CONDITIONERS ===\n")
        if not fabcon_df.empty:
            fabcon_df.to_csv(output, index=False)
        else:
            output.write("No fabric conditioners consumed\n")
        output.write(f"\n=== SUMMARY ===\n")
        output.write(f"Total Detergents: {inv_total_detergent_qty} pcs, Cost: {inv_total_detergent_cost:.2f}\n")
        output.write(f"Total Fabric Conditioners: {inv_total_fabcon_qty} pcs, Cost: {inv_total_fabcon_cost:.2f}\n")
        output.write(f"TOTAL: {inv_total_qty} pcs, Cost: {inv_total_cost:.2f}\n")
        output.seek(0)
        return send_file(io.BytesIO(output.getvalue().encode()), download_name=f"{filename}.csv", as_attachment=True, mimetype='text/csv')
    
    elif format == 'pdf':
        pdf = FPDF(orientation='L', unit='mm', format='legal')
        pdf.set_auto_page_break(auto=True, margin=15)

        def break_header(text):
            if not text:
                return ''
            if '_' in text:
                return '\n'.join(text.split('_'))
            parts = text.split(' ')
            if len(text) > 14 and len(parts) > 1:
                return '\n'.join(parts)
            return text

        def estimate_lines(text, width, font_size):
            pdf.set_font('Arial', '', font_size)
            if text is None or text == '':
                return 1
            text = str(text)
            blocks = text.split('\n')
            total = 0
            for block in blocks:
                words = block.split(' ')
                current = ''
                lines = 1
                for word in words:
                    candidate = word if current == '' else f"{current} {word}"
                    if pdf.get_string_width(candidate) <= max(width - 2, 1):
                        current = candidate
                    else:
                        lines += 1
                        current = word
                total += lines
            return max(total, 1)

        def add_title_bar(title):
            pdf.set_fill_color(18, 45, 105)  # #122D69
            pdf.set_text_color(255, 255, 255)
            pdf.set_font('Arial', 'B', 14)
            pdf.cell(0, 12, title, ln=True, align='C', fill=True)
            pdf.ln(3)

        def add_logo():
            try:
                pdf.image('static/images/pdfheader.jpg', x=10, y=8, w=78)
                pdf.ln(18)
            except Exception:
                pass

        def add_table(df, columns_config):
            if df.empty:
                pdf.set_text_color(200, 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 7, 'No data available.', ln=True, align='C')
                return
            
            available_width = pdf.w - 2 * pdf.l_margin
            col_widths = [available_width * w for w in columns_config]
            columns = [break_header(c) for c in df.columns]

            header_line_height = 5
            body_line_height = 4.5

            def render_header():
                pdf.set_font('Arial', 'B', 9)
                pdf.set_fill_color(245, 247, 250)
                pdf.set_text_color(35, 56, 114)
                max_header_lines = 1
                for header, width in zip(columns, col_widths):
                    max_header_lines = max(max_header_lines, estimate_lines(header, width, 9))
                header_height = max_header_lines * header_line_height
                y_start = pdf.get_y()
                for header, width in zip(columns, col_widths):
                    x_start = pdf.get_x()
                    pdf.multi_cell(width, header_line_height, header, border=1, align='C', fill=True)
                    pdf.set_xy(x_start + width, y_start)
                pdf.ln(header_height)
                pdf.set_text_color(0, 0, 0)

            render_header()
            pdf.set_font('Arial', '', 8)
            for row_idx, row in df.iterrows():
                if str(row.iloc[0]) == 'SUBTOTAL':
                    pdf.set_fill_color(230, 236, 250)
                    font_style = 'B'
                else:
                    font_style = ''
                    pdf.set_fill_color(248, 250, 252) if row_idx % 2 == 0 else pdf.set_fill_color(255, 255, 255)

                pdf.set_font('Arial', font_style, 8)
                max_lines = 1
                for idx, (item, width, col_name) in enumerate(zip(row, col_widths, columns)):
                    display_text = f"P{item:,.2f}" if isinstance(item, (int, float)) and ('Unit Price' in col_name or 'Total Cost' in col_name) else str(item)
                    max_lines = max(max_lines, estimate_lines(display_text, width, 8))
                row_height = max_lines * body_line_height
                if pdf.get_y() + row_height > pdf.page_break_trigger:
                    pdf.add_page()
                    render_header()
                y_start = pdf.get_y()
                for item, width, col_name in zip(row, col_widths, columns):
                    display_text = f"P{item:,.2f}" if isinstance(item, (int, float)) and ('Unit Price' in col_name or 'Total Cost' in col_name) else str(item)
                    x_start = pdf.get_x()
                    pdf.multi_cell(width, body_line_height, display_text, border=1, align='C', fill=True)
                    pdf.set_xy(x_start + width, y_start)
                pdf.ln(row_height)

                if str(row.iloc[0]) == 'SUBTOTAL':
                    pdf.set_font('Arial', '', 8)

        # Page 1: Consumed Detergents
        pdf.add_page()
        add_logo()
        pdf.set_font('Arial', 'B', 16)
        pdf.set_text_color(35, 56, 114)
        pdf.cell(0, 10, f'Inventory Consumption Report - {inv_period_label}', ln=True, align='C')
        pdf.ln(5)
        
        add_title_bar('Consumed Detergents')
        col_config = [0.10, 0.25, 0.12, 0.12, 0.10, 0.15, 0.10]
        add_table(det_df, col_config)
        
        # Page 2: Consumed Fabric Conditioners
        pdf.add_page()
        add_logo()
        add_title_bar('Consumed Fabric Conditioners')
        add_table(fabcon_df, col_config)
        
        # Summary section
        pdf.ln(10)
        add_title_bar('Inventory Consumption Summary')
        pdf.set_font('Arial', '', 11)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, f"Detergents Consumed: {inv_total_detergent_qty} pcs | Cost: P{inv_total_detergent_cost:,.2f}", ln=True)
        pdf.cell(0, 8, f"Fabric Conditioners Consumed: {inv_total_fabcon_qty} pcs | Cost: P{inv_total_fabcon_cost:,.2f}", ln=True)
        pdf.set_font('Arial', 'B', 12)
        pdf.set_text_color(35, 56, 114)
        pdf.cell(0, 10, f"TOTAL: {inv_total_qty} pcs | Total Cost: P{inv_total_cost:,.2f}", ln=True)
        
        output = io.BytesIO(pdf.output(dest='S').encode('latin1'))
        output.seek(0)
        return send_file(output, download_name=f"{filename}.pdf", as_attachment=True)
    
    else:
        return "Invalid format", 400

# INCOME STATEMENT
@app.route('/income_statement', methods=['GET'])
def income_statement():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
    
    # Get filter parameters
    view = request.args.get('view', 'daily')
    customer_id = request.args.get('customer_id', type=int)
    selected_month = request.args.get('month', '')  # Format: YYYY-MM
    selected_date = request.args.get('selected_date', '')  # Format: YYYY-MM-DD
    
    # Pagination parameters
    customer_page = request.args.get('customer_page', 1, type=int)
    order_page = request.args.get('order_page', 1, type=int)
    per_page = 15  # 15 items per page (between 10-20)
    
    # Expense inputs
    maintenance_repairs = float(request.args.get('maintenance_repairs', 0.0))
    
    # Get all orders
    all_orders = dbhelper.get_all_orders_with_priority()
    
    # Get inventory data for Inventory Page tab
    all_detergents = dbhelper.get_all_detergents()
    all_fabric_conditioners = dbhelper.get_all_fabric_conditioners()
    low_stock_detergents = [d for d in all_detergents if d.get('QTY', 0) <= 10]
    low_stock_fabcons = [f for f in all_fabric_conditioners if f.get('QTY', 0) <= 10]
    total_detergents_count = len(all_detergents)
    total_fabcons_count = len(all_fabric_conditioners)
    low_stock_detergents_count = len(low_stock_detergents)
    low_stock_fabcons_count = len(low_stock_fabcons)
    
    # Calculate date range based on view
    now = datetime.now()
    if view == 'daily':
        if selected_date:
            # Parse selected date (YYYY-MM-DD format)
            try:
                selected_dt = datetime.strptime(selected_date, '%Y-%m-%d')
                start_date = selected_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = selected_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                period_label = f"Date: {selected_dt.strftime('%B %d, %Y')}"
            except (ValueError, AttributeError):
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
                period_label = f"Today: {now.strftime('%B %d, %Y')}"
                selected_date = now.strftime('%Y-%m-%d')
        else:
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            period_label = f"Today: {now.strftime('%B %d, %Y')}"
            selected_date = now.strftime('%Y-%m-%d')
    elif view == 'weekly':
        start_date = now - timedelta(days=7)
        end_date = now
        period_label = f"Week of {start_date.strftime('%B %d')} - {now.strftime('%B %d, %Y')}"
    elif view == 'monthly':
        if selected_month:
            # Parse selected month (YYYY-MM format)
            try:
                year, month = map(int, selected_month.split('-'))
                start_date = datetime(year, month, 1)
                if month == 12:
                    end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
                else:
                    end_date = datetime(year, month + 1, 1) - timedelta(days=1)
                end_date = end_date.replace(hour=23, minute=59, second=59)
                period_label = f"Month of {start_date.strftime('%B %Y')}"
            except (ValueError, AttributeError):
                start_date = now.replace(day=1)
                end_date = now
                period_label = f"Month of {now.strftime('%B %Y')}"
        else:
            start_date = now.replace(day=1)
            end_date = now
            period_label = f"Month of {now.strftime('%B %Y')}"
    elif view == 'yearly':
        start_date = now.replace(month=1, day=1)
        end_date = now
        period_label = f"Year {now.year}"
    else:
        start_date = now - timedelta(days=7)
        end_date = now
        period_label = f"Week of {start_date.strftime('%B %d')} - {now.strftime('%B %d, %Y')}"
    
    # Helper function to make datetime naive (timezone-unaware)
    def make_naive(dt):
        if dt is None:
            return None
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    
    # Get order report data for Order Page tab (all orders, not just completed)
    all_orders_for_report = []
    for order in all_orders:
        order_date = order.get('DATE_CREATED')
        if order_date:
            # Handle datetime objects
            if hasattr(order_date, 'date'):
                order_date_only = order_date.date()
                order_datetime = order_date if isinstance(order_date, datetime) else datetime.combine(order_date_only, datetime.min.time())
            elif isinstance(order_date, datetime):
                order_date_only = order_date.date()
                order_datetime = order_date
            else:
                continue
            
            # Convert to naive datetime for comparison
            order_datetime = make_naive(order_datetime)
            
            # Check date range
            if hasattr(start_date, 'date'):
                start_date_only = start_date.date()
            else:
                start_date_only = start_date
            
            # Ensure start_date and end_date are naive
            start_date_naive = make_naive(start_date)
            end_date_naive = make_naive(end_date)
            
            # Check if order is within date range
            in_range = False
            if view == 'daily' or (view == 'monthly' and selected_month):
                in_range = start_date_naive <= order_datetime <= end_date_naive
            else:
                in_range = order_date_only >= start_date_only
            
            if in_range:
                # Check customer filter
                if customer_id is None or order.get('CUSTOMER_ID') == customer_id:
                    all_orders_for_report.append(order)
    
    # Calculate order report metrics
    total_orders_count = len(all_orders_for_report)
    total_order_revenue = sum(float(o.get('TOTAL_PRICE', 0) or 0) for o in all_orders_for_report)
    pending_orders_count = len([o for o in all_orders_for_report if (o.get('ORDER_STATUS') or '').lower() == 'pending'])
    completed_orders_count = len([o for o in all_orders_for_report if (o.get('ORDER_STATUS') or '').lower() == 'completed'])
    pickup_orders_count = len([o for o in all_orders_for_report if (o.get('ORDER_STATUS') or '').lower() in ['pickup', 'pick-up']])
    
    # Filter orders by date range and customer (for Main Page - completed orders only)
    filtered_orders = []
    for order in all_orders:
        order_date = order.get('DATE_CREATED')
        if order_date:
            # Handle datetime objects
            if hasattr(order_date, 'date'):
                order_date_only = order_date.date()
                order_datetime = order_date if isinstance(order_date, datetime) else datetime.combine(order_date_only, datetime.min.time())
            elif isinstance(order_date, datetime):
                order_date_only = order_date.date()
                order_datetime = order_date
            else:
                continue
            
            # Convert to naive datetime for comparison
            order_datetime = make_naive(order_datetime)
            
            # Check date range
            if hasattr(start_date, 'date'):
                start_date_only = start_date.date()
            else:
                start_date_only = start_date
            
            # Ensure start_date and end_date are naive
            start_date_naive = make_naive(start_date)
            end_date_naive = make_naive(end_date)
            
            # Check if order is within date range
            in_range = False
            if view == 'daily' or (view == 'monthly' and selected_month):
                # For daily or monthly with specific month, check if order is within that range
                in_range = start_date_naive <= order_datetime <= end_date_naive
            else:
                # For other views, check if order is after start date
                in_range = order_date_only >= start_date_only
            
            if in_range:
                # Include pick-up and completed orders (processed orders)
                order_status = (order.get('ORDER_STATUS') or '').lower()
                if order_status in ['pick-up', 'pickup', 'completed']:
                    # Check customer filter
                    if customer_id is None or order.get('CUSTOMER_ID') == customer_id:
                        filtered_orders.append(order)
    
    # Calculate metrics
    total_transactions = len(filtered_orders)
    total_sales_with_tax = sum(float(o.get('TOTAL_PRICE', 0) or 0) for o in filtered_orders)
    
    # Calculate total tax - if TAX field exists in order, use it; otherwise calculate from TOTAL_PRICE
    total_tax = 0.0
    for o in filtered_orders:
        tax_val = float(o.get('TAX') or 0)
        if tax_val > 0:
            # TAX field has value, use it
            total_tax += tax_val
        else:
            # TAX field is missing/0, calculate it as TOTAL_PRICE / 1.12 * 0.12
            total_price = float(o.get('TOTAL_PRICE', 0) or 0)
            if total_price > 0:
                calculated_tax = (total_price / 1.12) * 0.12
                total_tax += calculated_tax
    
    total_sales = total_sales_with_tax - total_tax  # Sales before tax
    
    # Calculate service sales (from orders with ORDER_TYPE)
    service_sales = total_sales  # This is our revenue before tax
    other_sales = 0.0
    
    # Count services for best/slowest selling
    # Include: Order types, Detergents, Fabric Conditioners, Additional Services (Iron, Fold, Priority), Pickup Schedule
    service_counts = {}
    detergent_counts = {}  # Separate counts for detergents only
    fabcon_counts = {}  # Separate counts for fabric conditioners only
    
    for order in filtered_orders:
        order_type = order.get('ORDER_TYPE', '').strip()
        if order_type:
            service_counts[order_type] = service_counts.get(order_type, 0) + 1
        
        # Get order item details
        orderitem_id = order.get('ORDERITEM_ID')
        if orderitem_id:
            orderitem = dbhelper.get_orderitem_by_id(orderitem_id)
            if orderitem:
                # Count additional services
                if orderitem.get('IRON'):
                    service_counts['Iron'] = service_counts.get('Iron', 0) + 1
                if orderitem.get('FOLD_CLOTHES'):
                    service_counts['Fold'] = service_counts.get('Fold', 0) + 1
                if orderitem.get('PRIORITIZE_ORDER'):
                    service_counts['Priority'] = service_counts.get('Priority', 0) + 1
                
                # Count detergents
                if not orderitem.get('CUSTOMER_OWN_DETERGENT'):
                    detergents = dbhelper.get_orderitem_detergents(orderitem_id)
                    for det in detergents:
                        det_name = det.get('DETERGENT_NAME', 'Unknown Detergent')
                        service_counts[f'Detergent: {det_name}'] = service_counts.get(f'Detergent: {det_name}', 0) + 1
                        # Count for detergent-specific tracking
                        detergent_counts[det_name] = detergent_counts.get(det_name, 0) + 1
                
                # Count fabric conditioners
                if not orderitem.get('CUSTOMER_OWN_FABCON'):
                    fabcons = dbhelper.get_orderitem_fabcons(orderitem_id)
                    for fab in fabcons:
                        fab_name = fab.get('FABCON_NAME', 'Unknown Fabcon')
                        service_counts[f'Fabric Conditioner: {fab_name}'] = service_counts.get(f'Fabric Conditioner: {fab_name}', 0) + 1
                        # Count for fabcon-specific tracking
                        fabcon_counts[fab_name] = fabcon_counts.get(fab_name, 0) + 1
        
        # Count pickup schedule
        if order.get('PICKUP_SCHEDULE'):
            service_counts['Scheduled Pickup'] = service_counts.get('Scheduled Pickup', 0) + 1
    
    # Determine best selling service
    best_selling_service = 'N/A'
    if service_counts:
        # Sort by count (descending - highest first)
        sorted_services = sorted(service_counts.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_services) > 0:
            best_selling_service = sorted_services[0][0]
    
    # Determine best and slowest selling detergents
    best_selling_detergent = 'N/A'
    slowest_selling_detergent = 'N/A'
    if detergent_counts:
        # Use order data if available
        sorted_detergents = sorted(detergent_counts.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_detergents) > 0:
            best_selling_detergent = sorted_detergents[0][0]
            slowest_selling_detergent = sorted_detergents[-1][0]  # Last item is slowest
    elif all_detergents:
        # Fallback: Use inventory stock levels (lowest stock = best selling assumption)
        sorted_by_stock = sorted(all_detergents, key=lambda x: x.get('QTY', 0))
        if len(sorted_by_stock) > 0:
            best_selling_detergent = sorted_by_stock[0].get('DETERGENT_NAME', 'N/A')
            slowest_selling_detergent = sorted_by_stock[-1].get('DETERGENT_NAME', 'N/A')
    
    # Determine best and slowest selling fabric conditioners
    best_selling_fabcon = 'N/A'
    slowest_selling_fabcon = 'N/A'
    if fabcon_counts:
        # Use order data if available
        sorted_fabcons = sorted(fabcon_counts.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_fabcons) > 0:
            best_selling_fabcon = sorted_fabcons[0][0]
            slowest_selling_fabcon = sorted_fabcons[-1][0]  # Last item is slowest
    elif all_fabric_conditioners:
        # Fallback: Use inventory stock levels (lowest stock = best selling assumption)
        sorted_by_stock = sorted(all_fabric_conditioners, key=lambda x: x.get('QTY', 0))
        if len(sorted_by_stock) > 0:
            best_selling_fabcon = sorted_by_stock[0].get('FABCON_NAME', 'N/A')
            slowest_selling_fabcon = sorted_by_stock[-1].get('FABCON_NAME', 'N/A')
    
    net_sales = service_sales + other_sales
    
    # Calculate COGS from orders (30% of revenue - cost of detergents, fabcons, utilities)
    total_cogs = net_sales * 0.30
    
    # Calculate expenses
    total_opex = maintenance_repairs
    gross_profit = net_sales - total_cogs
    operating_income = gross_profit - total_opex
    income_before_tax = operating_income
    income_tax_amount = 0
    net_income = income_before_tax
    
    # Get all customers for dropdown
    customers = dbhelper.get_all_customers()
    
    # Calculate breakdowns
    customers_breakdown = []
    orders_breakdown = []
    
    # Group by customer
    customer_dict = {}
    for order in filtered_orders:
        cid = order.get('CUSTOMER_ID')
        if cid not in customer_dict:
            customer_dict[cid] = {
                'CUSTOMER_ID': cid,
                'Orders': 0,
                'Revenue': 0.0,
                'OtherSales': 0.0,
                'COGS': 0.0,
                'Net': 0.0
            }
        customer_dict[cid]['Orders'] += 1
        revenue = float(order.get('TOTAL_PRICE', 0) or 0)
        customer_dict[cid]['Revenue'] += revenue
    
    # Prepare customers breakdown (without names, using customer IDs)
    all_customers_breakdown = []
    for cid, data in customer_dict.items():
        # Estimate COGS (simplified - 30% of revenue)
        data['COGS'] = data['Revenue'] * 0.3
        data['Net'] = data['Revenue'] - data['COGS']
        all_customers_breakdown.append(data)
    
    # Paginate customers breakdown
    total_customer_pages = (len(all_customers_breakdown) + per_page - 1) // per_page if all_customers_breakdown else 1
    customer_page = max(1, min(customer_page, total_customer_pages)) if total_customer_pages > 0 else 1
    start_customer_idx = (customer_page - 1) * per_page
    end_customer_idx = start_customer_idx + per_page
    customers_breakdown = all_customers_breakdown[start_customer_idx:end_customer_idx]
    
    # Create customer lookup dictionary for quick access
    customer_lookup = {c['CUSTOMER_ID']: c for c in customers}
    
    # Orders breakdown - prepare only completed orders with customer information
    all_orders_breakdown = []
    for order in filtered_orders:
        # Only include completed orders in the Order Details table
        order_status = (order.get('ORDER_STATUS') or '').lower()
        if order_status != 'completed':
            continue
        
        cust_id = order.get('CUSTOMER_ID')
        customer_info = customer_lookup.get(cust_id, {})
        
        # Calculate tax - if TAX field exists and is > 0, use it; otherwise calculate from TOTAL_PRICE
        total_price = float(order.get('TOTAL_PRICE', 0) or 0)
        tax_value = float(order.get('TAX') or 0)
        if tax_value <= 0:
            # TAX field missing/0, calculate it as TOTAL_PRICE / 1.12 * 0.12
            tax_value = (total_price / 1.12) * 0.12 if total_price > 0 else 0
        
        revenue = total_price - tax_value
        cogs = revenue * 0.3
        net = revenue * 0.7
        
        all_orders_breakdown.append({
            'ORDER_ID': order.get('ORDER_ID'),
            'CUSTOMER_ID': cust_id,
            'CUSTOMER_NAME': customer_info.get('FULLNAME', 'N/A'),
            'PHONE_NUMBER': customer_info.get('PHONE_NUMBER', 'N/A'),
            'ORDER_TYPE': order.get('ORDER_TYPE', 'N/A'),
            'ORDER_STATUS': order.get('ORDER_STATUS', 'N/A'),
            'Revenue': revenue,
            'Tax': tax_value,
            'COGS': cogs,
            'Net': net
        })
    
    # Calculate completed orders summary totals
    completed_total_revenue = sum(o['Revenue'] for o in all_orders_breakdown)
    completed_total_cogs = sum(o['COGS'] for o in all_orders_breakdown)
    completed_total_net = sum(o['Net'] for o in all_orders_breakdown)
    completed_orders_count = len(all_orders_breakdown)

    net_sales = completed_total_revenue
    total_cogs = completed_total_cogs
    total_opex = maintenance_repairs
    gross_profit = net_sales - total_cogs
    income_before_tax = gross_profit - total_opex
    income_tax_amount = 0
    net_income = income_before_tax
    
    # Paginate orders breakdown
    total_order_pages = (len(all_orders_breakdown) + per_page - 1) // per_page if all_orders_breakdown else 1
    order_page = max(1, min(order_page, total_order_pages)) if total_order_pages > 0 else 1
    start_order_idx = (order_page - 1) * per_page
    end_order_idx = start_order_idx + per_page
    orders_breakdown = all_orders_breakdown[start_order_idx:end_order_idx]
    
    return render_template(
        'admin_incostate_report.html',
        view=view,
        start='',
        end='',
        selected_month=selected_month,
        selected_date=selected_date,
        customer_id=customer_id,
        customers=customers,
        max=max,
        maintenance_repairs=maintenance_repairs,
        period_label=period_label,
        service_sales=service_sales,
        other_sales=other_sales,
        net_sales=net_sales,
        total_cogs=total_cogs,
        total_opex=total_opex,
        gross_profit=gross_profit,
        operating_income=operating_income,
        income_before_tax=income_before_tax,
        net_income=net_income,
        total_transactions=total_transactions,
        total_tax=total_tax,
        best_selling_service=best_selling_service,
        customers_breakdown=customers_breakdown,
        all_customers_breakdown=all_customers_breakdown,  # For modals
        orders_breakdown=orders_breakdown,
        completed_total_revenue=completed_total_revenue,
        completed_total_cogs=completed_total_cogs,
        completed_total_net=completed_total_net,
        completed_orders_total=completed_orders_count,
        customer_page=customer_page,
        order_page=order_page,
        total_customer_pages=total_customer_pages,
        total_order_pages=total_order_pages,
        per_page=per_page,
        # Inventory Page data
        all_detergents=all_detergents,
        all_fabric_conditioners=all_fabric_conditioners,
        total_detergents_count=total_detergents_count,
        total_fabcons_count=total_fabcons_count,
        low_stock_detergents_count=low_stock_detergents_count,
        low_stock_fabcons_count=low_stock_fabcons_count,
        best_selling_detergent=best_selling_detergent,
        slowest_selling_detergent=slowest_selling_detergent,
        best_selling_fabcon=best_selling_fabcon,
        slowest_selling_fabcon=slowest_selling_fabcon,
        # Order Page data
        total_orders_count=total_orders_count,
        total_order_revenue=total_order_revenue,
        pending_orders_count=pending_orders_count,
        completed_orders_count=completed_orders_count,
        pickup_orders_count=pickup_orders_count
)

@app.route('/download_income_statement/<format>')
def download_income_statement(format):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
    
    # Get filter parameters (same as income_statement route)
    view = request.args.get('view', 'daily')
    customer_id = request.args.get('customer_id', type=int)
    selected_month = request.args.get('month', '')
    selected_date = request.args.get('selected_date', '')  # Format: YYYY-MM-DD
    
    # Expense inputs
    maintenance_repairs = float(request.args.get('maintenance_repairs', 0.0))
    
    # Get all orders
    all_orders = dbhelper.get_all_orders_with_priority()
    
    # Get inventory data
    all_detergents = dbhelper.get_all_detergents()
    all_fabric_conditioners = dbhelper.get_all_fabric_conditioners()
    total_detergents_count = len(all_detergents)
    total_fabcons_count = len(all_fabric_conditioners)
    
    # Calculate date range based on view
    now = datetime.now()
    if view == 'daily':
        if selected_date:
            try:
                selected_dt = datetime.strptime(selected_date, '%Y-%m-%d')
                start_date = selected_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = selected_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                period_label = f"Date: {selected_dt.strftime('%B %d, %Y')}"
            except (ValueError, AttributeError):
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
                period_label = f"Today: {now.strftime('%B %d, %Y')}"
        else:
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            period_label = f"Today: {now.strftime('%B %d, %Y')}"
    elif view == 'weekly':
        start_date = now - timedelta(days=7)
        end_date = now
        period_label = f"Week of {start_date.strftime('%B %d')} - {now.strftime('%B %d, %Y')}"
    elif view == 'monthly':
        if selected_month:
            # Parse selected month (YYYY-MM format)
            try:
                year, month = map(int, selected_month.split('-'))
                start_date = datetime(year, month, 1)
                if month == 12:
                    end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
                else:
                    end_date = datetime(year, month + 1, 1) - timedelta(days=1)
                end_date = end_date.replace(hour=23, minute=59, second=59)
                period_label = f"Month of {start_date.strftime('%B %Y')}"
            except (ValueError, AttributeError):
                start_date = now.replace(day=1)
                end_date = now
                period_label = f"Month of {now.strftime('%B %Y')}"
        else:
            start_date = now.replace(day=1)
            end_date = now
            period_label = f"Month of {now.strftime('%B %Y')}"
    elif view == 'yearly':
        start_date = now.replace(month=1, day=1)
        end_date = now
        period_label = f"Year {now.year}"
    else:
        start_date = now - timedelta(days=7)
        end_date = now
        period_label = f"Week of {start_date.strftime('%B %d')} - {now.strftime('%B %d, %Y')}"
    
    # Helper function to make datetime naive (timezone-unaware)
    def make_naive_dt(dt):
        if dt is None:
            return None
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    
    # Filter completed orders
    filtered_orders = []
    for order in all_orders:
        order_date = order.get('DATE_CREATED')
        if order_date:
            if hasattr(order_date, 'date'):
                order_date_only = order_date.date()
                order_datetime = order_date if isinstance(order_date, datetime) else datetime.combine(order_date_only, datetime.min.time())
            elif isinstance(order_date, datetime):
                order_date_only = order_date.date()
                order_datetime = order_date
            else:
                continue
            
            # Convert to naive datetime for comparison
            order_datetime = make_naive_dt(order_datetime)
            
            if hasattr(start_date, 'date'):
                start_date_only = start_date.date()
            else:
                start_date_only = start_date
            
            # Ensure start_date and end_date are naive
            start_date_naive = make_naive_dt(start_date)
            end_date_naive = make_naive_dt(end_date)
            
            in_range = False
            if view == 'daily' or (view == 'monthly' and selected_month):
                in_range = start_date_naive <= order_datetime <= end_date_naive
            else:
                in_range = order_date_only >= start_date_only
            
            if in_range:
                # Include pick-up and completed orders (processed orders)
                order_status = (order.get('ORDER_STATUS') or '').lower()
                if order_status in ['pick-up', 'pickup', 'completed']:
                    if customer_id is None or order.get('CUSTOMER_ID') == customer_id:
                        filtered_orders.append(order)
    
    # Calculate metrics
    total_transactions = len(filtered_orders)
    total_sales = sum(float(o.get('TOTAL_PRICE', 0) or 0) for o in filtered_orders)
    
    # Count services for best/slowest selling
    # Include: Order types, Detergents, Fabric Conditioners, Additional Services (Iron, Fold, Priority), Pickup Schedule
    service_counts = {}
    for order in filtered_orders:
        order_type = order.get('ORDER_TYPE', '').strip()
        if order_type:
            service_counts[order_type] = service_counts.get(order_type, 0) + 1
        
        # Get order item details
        orderitem_id = order.get('ORDERITEM_ID')
        if orderitem_id:
            orderitem = dbhelper.get_orderitem_by_id(orderitem_id)
            if orderitem:
                # Count additional services
                if orderitem.get('IRON'):
                    service_counts['Iron'] = service_counts.get('Iron', 0) + 1
                if orderitem.get('FOLD_CLOTHES'):
                    service_counts['Fold'] = service_counts.get('Fold', 0) + 1
                if orderitem.get('PRIORITIZE_ORDER'):
                    service_counts['Priority'] = service_counts.get('Priority', 0) + 1
                
                # Count detergents
                if not orderitem.get('CUSTOMER_OWN_DETERGENT'):
                    detergents = dbhelper.get_orderitem_detergents(orderitem_id)
                    for det in detergents:
                        det_name = det.get('DETERGENT_NAME', 'Unknown Detergent')
                        service_counts[f'Detergent: {det_name}'] = service_counts.get(f'Detergent: {det_name}', 0) + 1
                
                # Count fabric conditioners
                if not orderitem.get('CUSTOMER_OWN_FABCON'):
                    fabcons = dbhelper.get_orderitem_fabcons(orderitem_id)
                    for fab in fabcons:
                        fab_name = fab.get('FABCON_NAME', 'Unknown Fabcon')
                        service_counts[f'Fabric Conditioner: {fab_name}'] = service_counts.get(f'Fabric Conditioner: {fab_name}', 0) + 1
        
        # Count pickup schedule
        if order.get('PICKUP_SCHEDULE'):
            service_counts['Scheduled Pickup'] = service_counts.get('Scheduled Pickup', 0) + 1
    
    best_selling_service = 'N/A'
    if service_counts:
        # Sort by count (descending - highest first) for best selling
        sorted_services = sorted(service_counts.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_services) > 0:
            best_selling_service = sorted_services[0][0]
    
    # Get all orders count
    all_orders_for_report = []
    for order in all_orders:
        order_date = order.get('DATE_CREATED')
        if order_date:
            if hasattr(order_date, 'date'):
                order_date_only = order_date.date()
                order_datetime = order_date if isinstance(order_date, datetime) else datetime.combine(order_date_only, datetime.min.time())
            elif isinstance(order_date, datetime):
                order_date_only = order_date.date()
                order_datetime = order_date
            else:
                continue
            
            # Convert to naive datetime for comparison
            order_datetime = make_naive_dt(order_datetime)
            
            if hasattr(start_date, 'date'):
                start_date_only = start_date.date()
            else:
                start_date_only = start_date
            
            # Ensure start_date and end_date are naive
            start_date_naive = make_naive_dt(start_date)
            end_date_naive = make_naive_dt(end_date)
            
            in_range = False
            if view == 'daily' or (view == 'monthly' and selected_month):
                in_range = start_date_naive <= order_datetime <= end_date_naive
            else:
                in_range = order_date_only >= start_date_only
            
            if in_range:
                if customer_id is None or order.get('CUSTOMER_ID') == customer_id:
                    all_orders_for_report.append(order)
    
    total_orders_count = len(all_orders_for_report)
    
    # Calculate COGS from orders (30% of revenue - cost of detergents, fabcons, utilities)
    net_sales = total_sales
    total_cogs = net_sales * 0.30
    
    # Calculate expenses
    total_opex = maintenance_repairs
    gross_profit = net_sales - total_cogs
    operating_income = gross_profit - total_opex
    income_before_tax = operating_income
    income_tax_amount = 0
    net_income = income_before_tax
    
    # Get customers for lookup
    customers = dbhelper.get_all_customers()
    customer_lookup = {c['CUSTOMER_ID']: c for c in customers}
    
    # Prepare completed orders data for export
    completed_orders_data = []
    for order in filtered_orders:
        order_status = (order.get('ORDER_STATUS') or '').lower()
        if order_status == 'completed':
            cust_id = order.get('CUSTOMER_ID')
            customer_info = customer_lookup.get(cust_id, {})
            revenue = float(order.get('TOTAL_PRICE', 0) or 0)
            completed_orders_data.append({
                'Order #': f"LL-{order.get('ORDER_ID')}",
                'Customer Name': customer_info.get('FULLNAME', 'N/A'),
                'Phone Number': customer_info.get('PHONE_NUMBER', 'N/A'),
                'Order Type': order.get('ORDER_TYPE', 'N/A'),
                'Revenue': revenue,
                'COGS': revenue * 0.3,
                'Net': revenue * 0.7
            })
    
    orders_df = pd.DataFrame(completed_orders_data)
    
    # Prepare data for export
    data = [{
        'Metric': 'Total Sales (Completed Orders)',
        'Value': f"₱ {net_sales:,.2f}"
    }, {
        'Metric': 'Total Transactions (Completed)',
        'Value': total_transactions
    }, {
        'Metric': 'Total Orders (All Status)',
        'Value': total_orders_count
    }, {
        'Metric': 'Total Inventory Items',
        'Value': total_detergents_count + total_fabcons_count
    }, {
        'Metric': 'Best Selling Service',
        'Value': best_selling_service
    }, {
        'Metric': 'Net Revenue',
        'Value': f"₱ {net_income:,.2f}"
    }]
    
    df = pd.DataFrame(data)
    filename = 'income_statement_report'
    
    if format == 'excel':
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Summary', index=False)
            if not orders_df.empty:
                orders_df.to_excel(writer, sheet_name='Completed Orders', index=False)
        output.seek(0)
        return send_file(output, download_name=f"{filename}.xlsx", as_attachment=True)
    elif format == 'csv':
        output = io.StringIO()
        output.write("=== SUMMARY ===\n")
        df.to_csv(output, index=False)
        output.write("\n\n=== COMPLETED ORDERS ===\n")
        if not orders_df.empty:
            orders_df.to_csv(output, index=False)
        else:
            output.write("No completed orders for this period\n")
        output.seek(0)
        return Response(output.getvalue(), mimetype='text/csv', headers={"Content-Disposition": f"attachment;filename={filename}.csv"})
    elif format == 'pdf':
        pdf = FPDF(orientation='P', unit='mm', format='letter')
        pdf.set_auto_page_break(auto=True, margin=15)
        
        def add_title_bar(title):
            pdf.set_fill_color(18, 45, 105)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font('Arial', 'B', 16)
            pdf.cell(0, 14, title, ln=True, align='C', fill=True)
            pdf.ln(2)
        
        def add_table(df):
            if df.empty:
                pdf.set_text_color(200, 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 7, 'No data available.', ln=True, align='C')
                return
        
            pdf.set_font('Arial', 'B', 10)
            pdf.set_fill_color(245, 247, 250)
            pdf.set_text_color(35, 56, 114)
            available_width = pdf.w - 2 * pdf.l_margin
            col_widths = [available_width * 0.6, available_width * 0.4]
            
            # Header
            pdf.cell(col_widths[0], 7, 'Metric', border=1, align='C', fill=True)
            pdf.cell(col_widths[1], 7, 'Value', border=1, align='C', fill=True)
            pdf.ln()
            
            # Table rows
            pdf.set_font('Arial', '', 9)
            for row_idx, row in df.iterrows():
                if row_idx % 2 == 0:
                    pdf.set_fill_color(248, 250, 252)  # #f8fafc
                else:
                    pdf.set_fill_color(255, 255, 255)  # white
                pdf.set_text_color(0, 0, 0)
                pdf.cell(col_widths[0], 7, str(row['Metric']), border=1, align='L', fill=True)
                pdf.cell(col_widths[1], 7, str(row['Value']), border=1, align='R', fill=True)
                pdf.ln()
        
        def add_orders_table(orders_df):
            if orders_df.empty:
                pdf.set_text_color(100, 100, 100)
                pdf.set_font('Arial', 'I', 10)
                pdf.cell(0, 10, 'No completed orders for this period', ln=True, align='C')
                return
            
            pdf.set_font('Arial', 'B', 8)
            pdf.set_fill_color(245, 247, 250)
            pdf.set_text_color(35, 56, 114)
            available_width = pdf.w - 2 * pdf.l_margin
            # Column widths for orders table
            col_widths = [available_width * 0.10, available_width * 0.22, available_width * 0.18, 
                         available_width * 0.14, available_width * 0.12, available_width * 0.12, available_width * 0.12]
            headers = ['Order #', 'Customer', 'Phone', 'Type', 'Revenue', 'COGS', 'Net']
            
            for i, header in enumerate(headers):
                pdf.cell(col_widths[i], 6, header, border=1, align='C', fill=True)
            pdf.ln()
            
            pdf.set_font('Arial', '', 7)
            for row_idx, row in orders_df.iterrows():
                if row_idx % 2 == 0:
                    pdf.set_fill_color(248, 250, 252)
                else:
                    pdf.set_fill_color(255, 255, 255)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(col_widths[0], 6, str(row['Order #']), border=1, align='C', fill=True)
                pdf.cell(col_widths[1], 6, str(row['Customer Name'])[:20], border=1, align='L', fill=True)
                pdf.cell(col_widths[2], 6, str(row['Phone Number'])[:15], border=1, align='L', fill=True)
                pdf.cell(col_widths[3], 6, str(row['Order Type'])[:12], border=1, align='C', fill=True)
                pdf.cell(col_widths[4], 6, f"{row['Revenue']:,.2f}", border=1, align='R', fill=True)
                pdf.cell(col_widths[5], 6, f"{row['COGS']:,.2f}", border=1, align='R', fill=True)
                pdf.cell(col_widths[6], 6, f"{row['Net']:,.2f}", border=1, align='R', fill=True)
                pdf.ln()
        
        pdf.add_page()
        add_title_bar('Income Statement Report')
        pdf.set_font('Arial', '', 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 7, f"Period: {period_label}", ln=True, align='L')
        pdf.ln(2)
        pdf_df = df.copy()
        if 'Value' in pdf_df.columns:
            pdf_df['Value'] = pdf_df['Value'].apply(lambda v: str(v).replace('₱', 'PHP'))
        add_table(pdf_df)
        
        # Add Completed Orders section
        pdf.ln(8)
        pdf.set_font('Arial', 'B', 12)
        pdf.set_text_color(18, 45, 105)
        pdf.cell(0, 8, 'Completed Orders', ln=True, align='L')
        pdf.ln(2)
        add_orders_table(orders_df)
        
        # Handle PDF output - fpdf2 returns bytes, fpdf returns string
        pdf_output = pdf.output(dest='S')
        if isinstance(pdf_output, str):
            pdf_bytes = pdf_output.encode('latin1')
        else:
            pdf_bytes = pdf_output
        output = io.BytesIO(pdf_bytes)
        output.seek(0)
        return send_file(output, download_name=f"{filename}.pdf", as_attachment=True, mimetype='application/pdf')
    else:
        return "Invalid format", 400

# Store latest weight in a global variable
latest_weight = 0.0
weight_is_stable = False
previous_weight = None
stable_count = 0

@app.route('/api/weight', methods=['POST'])
def api_weight():
    global latest_weight, weight_is_stable, previous_weight, stable_count
    data = request.get_json()
    try:
        # Weight is now sent in kilograms from ESP32
        new_weight = float(data.get('weight', 0.0))
        
        # Check if weight is stable (within 0.1 kg tolerance)
        if previous_weight is not None and abs(new_weight - previous_weight) < 0.1:
            stable_count += 1
            weight_is_stable = stable_count >= 3  # Stable after 3 consecutive reads within tolerance
        else:
            stable_count = 0
            weight_is_stable = False
        
        latest_weight = new_weight
        previous_weight = new_weight
    except Exception:
        latest_weight = 0.0
        weight_is_stable = False
        previous_weight = None
        stable_count = 0
    return jsonify({"status": "ok"})

@app.route('/get_latest_weight')
def get_latest_weight():
    global latest_weight, weight_is_stable
    return jsonify({"weight": latest_weight, "is_stable": weight_is_stable})

# Track if weight page is active
weight_page_active = False

@app.route('/weight_page_active', methods=['GET', 'POST'])
def weight_page_active_api():
    global weight_page_active
    if request.method == 'POST':
        data = request.get_json()
        weight_page_active = bool(data.get('active', False))
        return jsonify({"active": weight_page_active})
    else:
        return jsonify({"active": weight_page_active})

@app.route('/api/send_sms', methods=['POST'])
def api_send_sms():
    data = request.get_json()
    phone = data.get('phone')
    message = data.get('message')
    print("Forwarding SMS to ESP32:", phone, message)  # Debug print
    if not phone or not message:
        # FIX: Use correct dictionary syntax
        return jsonify({'status': 'error', 'msg': 'Missing phone or message'}), 400
    try:
        # Use the correct ESP32 IP address
        esp32_ip = os.getenv('ESP32_IP', '10.137.16.199')  # <-- Update default IP here
        esp32_url = f"http://{esp32_ip}:8080/send_sms_gsm"
        print("ESP32 URL:", esp32_url)  # Debug print
        resp = requests.post(esp32_url, json={"phone": phone, "message": message}, timeout=3)
        print("ESP32 response:", resp.text)  # Debug print
        if resp.status_code == 200:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'status': 'error', 'msg': 'ESP32 GSM error'}), 500
    except Exception as e:
        print("Error forwarding SMS to ESP32:", e)
        return jsonify({'status': 'error', 'msg': str(e)}), 500

# =================================================================================================================================
# THIS API HERE IS FOR THE STAFF AND ADMIN DASHBOARS, SPECIFICALLY FOR THE CALENDAR AND DATE DETAILS MODAL
# THE BLUE DOT ON DATES WITH ORDER
# YELLOW DOT ON DATES WITH PICKUPS
# API endpoint to get orders for a specific date
@app.route('/api/orders_by_date', methods=['GET'])
def api_orders_by_date():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return jsonify({'error': 'Unauthorized'}), 401

    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'error': 'Date parameter required'}), 400

    try:
        # Parse date (format: YYYY-MM-DD)
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        start_datetime = datetime.combine(target_date, datetime.min.time())
        end_datetime = datetime.combine(target_date, datetime.max.time())

        # Get all orders
        all_orders = dbhelper.get_all_orders_with_priority()

        # Filter orders for the target date
        orders_for_date = []
        for order in all_orders:
            date_created = order.get('DATE_CREATED')
            if date_created:
                # Handle both datetime and Firestore timestamp
                if hasattr(date_created, 'date'):
                    order_date = date_created.date()
                elif isinstance(date_created, datetime):
                    order_date = date_created.date()
                else:
                    continue

                if start_datetime.date() <= order_date <= end_datetime.date():
                    # Format time for display
                    if hasattr(date_created, 'strftime'):
                        order['TIME_FORMATTED'] = date_created.strftime('%I:%M %p')
                    else:
                        order['TIME_FORMATTED'] = 'N/A'
                    # Ensure defaults for missing values
                    order['TOTAL_LOAD'] = order.get('TOTAL_LOAD', 0)
                    order['TOTAL_PRICE'] = order.get('TOTAL_PRICE', 0.0)
                    orders_for_date.append(order)

        return jsonify({'orders': orders_for_date})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API endpoint to get pickups for a specific date
@app.route('/api/pickups_by_date', methods=['GET'])
def api_pickups_by_date():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return jsonify({'error': 'Unauthorized'}), 401
    
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'error': 'Date parameter required'}), 400
    
    try:
        # Parse date (format: YYYY-MM-DD)
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Get all orders
        all_orders = dbhelper.get_all_orders_with_priority()
        
        # Filter orders with pickup schedule for the target date
        pickups_for_date = []
        for order in all_orders:
            pickup_schedule = order.get('PICKUP_SCHEDULE')
            if pickup_schedule:
                # Parse pickup schedule (format: YYYY-MM-DD HH:MM:SS or YYYY-MM-DD)
                try:
                    if isinstance(pickup_schedule, str):
                        if ' ' in pickup_schedule:
                            pickup_datetime = datetime.strptime(pickup_schedule.split()[0], '%Y-%m-%d')
                        else:
                            pickup_datetime = datetime.strptime(pickup_schedule, '%Y-%m-%d')
                    else:
                        pickup_datetime = pickup_schedule
                    
                    if hasattr(pickup_datetime, 'date'):
                        pickup_date = pickup_datetime.date()
                    else:
                        pickup_date = pickup_datetime.date()
                    
                    if pickup_date == target_date:
                        # Ensure defaults for missing values
                        order['TOTAL_LOAD'] = order.get('TOTAL_LOAD', 0)
                        order['TOTAL_PRICE'] = order.get('TOTAL_PRICE', 0.0)
                        # Format pickup time
                        if isinstance(pickup_schedule, str) and ' ' in pickup_schedule:
                            time_part = pickup_schedule.split()[1]
                            if ':' in time_part:
                                hour, minute = time_part.split(':')[:2]
                                try:
                                    pickup_time = datetime.strptime(f"{hour}:{minute}", '%H:%M').strftime('%I:%M %p')
                                except:
                                    pickup_time = time_part
                            else:
                                pickup_time = time_part
                        else:
                            pickup_time = 'N/A'
                        order['PICKUP_TIME'] = pickup_time
                        order['ORDER_STATUS'] = order.get('ORDER_STATUS', 'Pending')
                        pickups_for_date.append(order)
                except:
                    pass
        
        return jsonify({'pickups': pickups_for_date})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API endpoint to get dates with orders (for calendar marking)
@app.route('/api/calendar_dates', methods=['GET'])
def api_calendar_dates():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # Get all orders
        all_orders = dbhelper.get_all_orders_with_priority()
        
        # Collect dates with orders
        dates_with_orders = set()
        dates_with_pickups = set()
        
        for order in all_orders:
            # Check DATE_CREATED
            date_created = order.get('DATE_CREATED')
            if date_created:
                if hasattr(date_created, 'date'):
                    order_date = date_created.date()
                elif isinstance(date_created, datetime):
                    order_date = date_created.date()
                else:
                    continue
                dates_with_orders.add(order_date.strftime('%Y-%m-%d'))
            
            # Check PICKUP_SCHEDULE
            pickup_schedule = order.get('PICKUP_SCHEDULE')
            if pickup_schedule:
                try:
                    if isinstance(pickup_schedule, str):
                        if ' ' in pickup_schedule:
                            pickup_datetime = datetime.strptime(pickup_schedule.split()[0], '%Y-%m-%d')
                        else:
                            pickup_datetime = datetime.strptime(pickup_schedule, '%Y-%m-%d')
                    else:
                        pickup_datetime = pickup_schedule
                    
                    if hasattr(pickup_datetime, 'date'):
                        pickup_date = pickup_datetime.date()
                    else:
                        pickup_date = pickup_datetime.date()
                    
                    if pickup_date.strftime('%Y-%m-%d') != order_date.strftime('%Y-%m-%d'):
                        dates_with_pickups.add(pickup_date.strftime('%Y-%m-%d'))
                except:
                    pass
        
        return jsonify({
            'dates_with_orders': list(dates_with_orders),
            'dates_with_pickups': list(dates_with_pickups)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
# =================================================================================================================================


@app.route('/api/pickup_orders')
def api_pickup_orders():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return jsonify({'error': 'Unauthorized'}), 401
    orders = get_all_orders_with_priority()
    pickup_orders = [
        o for o in orders
        if (o.get('ORDER_STATUS', '').lower() == 'pick-up')
    ]
    # Attach customer phone number and QR code if available
    for o in pickup_orders:
        customer = get_customer_by_id(o['CUSTOMER_ID']) if o.get('CUSTOMER_ID') else None
        o['PHONE_NUMBER'] = customer.get('PHONE_NUMBER') if customer else ''
        o['QR_CODE'] = o.get('QR_CODE', '')
    return jsonify({'orders': pickup_orders})

# COMPLETE PICK-UP API
@app.route('/api/complete_pickup/<int:order_id>', methods=['POST'])
def api_complete_pickup(order_id):
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return jsonify({'status': 'error', 'msg': 'Unauthorized'}), 401
    
    # Get order details
    order = dbhelper.get_order_by_id(order_id)
    if not order:
        return jsonify({'status': 'error', 'msg': 'Order not found'}), 404
    
    # Get customer details
    customer_id = order.get('CUSTOMER_ID')
    customer = dbhelper.get_customer_by_id(customer_id)
    if not customer:
        return jsonify({'status': 'error', 'msg': 'Customer not found'}), 404
    
    # Update order status to Completed
    user_id = session.get('user_id')
    dbhelper.update_order_status(order_id, 'Completed', user_id)
    
    # Send SMS notification to customer
    phone = customer.get('PHONE_NUMBER')
    customer_name = customer.get('FULLNAME')
    if phone:
        message = f"Hi {customer_name}, your laundry (Order #{order_id}) has been picked up. Thank you for using Laundrylink!"
        try:
            esp32_ip = os.getenv('ESP32_IP', '10.137.16.199')
            esp32_url = f"http://{esp32_ip}:8080/send_sms_gsm"
            requests.post(esp32_url, json={"phone": phone, "message": message}, timeout=3)
        except Exception as e:
            print(f"Error sending SMS: {e}")
    
    return jsonify({'status': 'success'})

# ============================== SUPER ADMIN ========================
@app.route('/super_admin_login', methods=['GET', 'POST'])
def super_admin_login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = authenticate_user(username, password)

        if user and user['ROLE'].lower() == 'super_admin':
            session['user_id'] = user['USER_ID']
            session['username'] = user['USERNAME']
            session['role'] = user['ROLE']
            return redirect(url_for('super_admin_dashboard')) 
        else:
            flash('Invalid username or password, or not a super admin account.', 'danger')
            return redirect(url_for('super_admin_login'))

    return render_template('super_admin_login.html', error=error)

@app.route('/super_admin_dashboard')
def super_admin_dashboard():
    if 'user_id' not in session or session['role'] not in ['super_admin']:
        return redirect(url_for('super_admin_login'))
    orders = dbhelper.get_all_orders_with_priority()
    current_month = datetime.now().month
    current_year = datetime.now().year
    monthly_earnings = 0.0

    for order in orders:
        date_created = order.get('DATE_CREATED')
        if date_created:
            if hasattr(date_created, 'date'):
                order_date = date_created.date()
            else:
                order_date = date_created

            order_price = float(order.get('TOTAL_PRICE', 0.0))

            if order_date.month == current_month and order_date.year == current_year:
                monthly_earnings += order_price

    order_stats = dbhelper.compute_order_stats(orders, days=7)
    order_status_counts = order_stats.get('status_counts', {})
    order_trend = order_stats.get('trend', {'labels': [], 'counts': []})
    
    # Calculate Shop/Device Stats
    shops = dbhelper.get_all_shops()
    installed_shops_count = len(shops)
    
    # Kiosk (and implicitly ESP32) offline count
    offline_kiosk_count = sum(1 for s in shops if s.get('kiosk', {}).get('status') != 'online')
    total_offline_devices = offline_kiosk_count
                
    return render_template('super_admin_dashboard.html', 
                           monthly_earnings=monthly_earnings, 
                           order_status_counts=order_status_counts, 
                           order_trend=order_trend,
                           installed_shops_count=installed_shops_count,
                           total_offline_devices=total_offline_devices,
                           offline_kiosk_count=offline_kiosk_count)

@app.route('/super_admin/shops')
def laundry_shops():
    if 'user_id' not in session or session['role'] not in ['super_admin']:
        return redirect(url_for('super_admin_login'))
    
    shops = dbhelper.get_all_shops()
    return render_template('super_admin_shops.html', shops=shops)

@app.route('/super_admin/devices')
def device_monitoring():
    if 'user_id' not in session or session['role'] not in ['super_admin']:
        return redirect(url_for('super_admin_login'))
    
    # Reusing shop data since devices are tied to shops
    shops = dbhelper.get_all_shops()
    return render_template('super_admin_devices.html', shops=shops)

@app.route('/super_admin/transactions')
def super_admin_transactions():
    if 'user_id' not in session or session['role'] not in ['super_admin']:
        return redirect(url_for('super_admin_login'))
    
    return render_template('super_admin_transaction.html')

@app.route('/super_admin/reports')
def super_admin_reports():
    if 'user_id' not in session or session['role'] not in ['super_admin']:
        return redirect(url_for('super_admin_login'))
    
    return render_template('super_admin_reports.html')

@app.route('/super_admin/add_shop', methods=['POST'])
def add_shop():
    if 'user_id' not in session or session['role'] not in ['super_admin']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    try:
        data = request.get_json()
        fullname = data.get('fullname')
        username = data.get('username')
        password = data.get('password')

        if not fullname or not username or not password:
            return jsonify({'success': False, 'message': 'All fields are required'})

        # Role is always 'admin' for a shop
        if dbhelper.add_user(username, password, 'admin', fullname):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Failed to create shop'})
    except Exception as e:
        print(f"Error adding shop: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/super_admin/update_device_status', methods=['POST'])
def update_device_status_route():
    if 'user_id' not in session or session['role'] not in ['super_admin']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    try:
        data = request.get_json()
        user_id_val = data.get('user_id')
        status = data.get('status') # 'online' or 'offline'

        if not user_id_val or not status:
            return jsonify({'success': False, 'message': 'Missing user_id or status'})

        if dbhelper.update_device_status(int(user_id_val), status):
            return jsonify({'success': True})
        else:
             return jsonify({'success': False, 'message': 'Failed to update status'})
    except Exception as e:
        print(f"Error updating device status: {e}")
        return jsonify({'success': False, 'message': str(e)})


    
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')