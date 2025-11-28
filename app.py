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
        
        flash('Customer information saved!')
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
            total_load = int(total_load_str) if total_load_str else 0
        except ValueError:
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

    # Calculate totals
    total_price = 0.0

    # Load price (50 per load)
    total_price += total_load * 50

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
            total_price += qty * price

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
            total_price += qty * price

    # Additional service costs
    if iron:
        total_price += 50.00
    if fold:
        total_price += 70.00
    if priority:
        total_price += 50.00
    
    # Store all order data in session instead of saving to DB
    session['order_data'] = {
        'order_type': session.get('order_type', 'Drop-off'),
        'total_weight': total_weight,
        'total_load': total_load,
        'total_price': total_price,
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
        
        # Add fabcons to junction table
        if not order_data['own_fabcon']:
            for fab in order_data['fabcon_details']:
                dbhelper.add_orderitem_fabcon(
                    orderitem_id,
                    fab['fabcon_id'],
                    fab['quantity'],
                    fab['unit_price']
                )
        
        # Create ORDER record
        order_id = dbhelper.add_order(
            customer_id=customer_id,
            orderitem_id=orderitem_id,
            user_id=None,
            order_type=order_data['order_type'],
            total_weight=order_data['total_weight'],
            total_load=order_data['total_load'],
            total_price=order_data['total_price'],
            order_note=order_data['order_note'],
            pickup_schedule=order_data['pickup_schedule'],
            order_status='Pending',
            payment_method=payment_method,
            payment_status='PAID'
        )
        
        # Generate QR code
        qr_img = qrcode.make(str(order_id))
        qr_filename = f"qr_order_{order_id}.png"
        qr_filepath = os.path.join(app.static_folder, "qr", qr_filename)
        os.makedirs(os.path.dirname(qr_filepath), exist_ok=True)
        qr_img.save(qr_filepath)
        qr_code_path = f"qr/{qr_filename}"
        dbhelper.update_order_qr_code(order_id, qr_code_path)

        # Receipt printing for cash payments
        if payment_method and payment_method.lower() == 'cash':
            try:
                from escpos.printer import Usb
                p = Usb(0x0483, 0x5743, encoding='GB18030')

                order = dbhelper.get_order_by_id(order_id)
                orderitem = dbhelper.get_orderitem_by_id(orderitem_id)
                orderitem_detergents = []
                if not order_data['own_detergent']:
                    orderitem_detergents = dbhelper.get_orderitem_detergents(orderitem_id)
                orderitem_fabcons = []
                if not order_data['own_fabcon']:
                    orderitem_fabcons = dbhelper.get_orderitem_fabcons(orderitem_id)

                lines = []
                lines.append("Laundry Link Receipt\n")
                lines.append(f"Order ID: {order.get('ORDER_ID')}\n")
                lines.append(f"Customer: {latest_customer.get('FULLNAME')}\n")
                lines.append(f"Phone: {latest_customer.get('PHONE_NUMBER')}\n")
                lines.append(f"Order Type: {order.get('ORDER_TYPE')}\n")
                lines.append(f"Status: {order.get('ORDER_STATUS')}\n")
                lines.append(f"Payment: {order.get('PAYMENT_STATUS')}\n")
                lines.append(f"Payment Method: {order.get('PAYMENT_METHOD')}\n")
                lines.append(f"Date Created: {datetime.now().strftime('%Y-%m-%d')}\n")
                lines.append(f"Pickup Schedule: {order.get('PICKUP_SCHEDULE')}\n")
                lines.append(f"Total Weight: {order.get('TOTAL_WEIGHT')} kg\n")
                lines.append(f"Order Notes: {order.get('ORDER_NOTE') or 'None'}\n")
                lines.append("-" * 32 + "\n")
                # Load
                if order.get('TOTAL_LOAD'):
                    lines.append(f"Total Load: {order.get('TOTAL_LOAD')} Loads\n")
                    lines.append(f"Load Price: ₱{order.get('TOTAL_LOAD') * 50:.2f}\n")
                # Priority
                if order_data['priority']:
                    lines.append("Priority: ₱50.00\n")
                # Iron
                if order_data['iron']:
                    lines.append("Ironing: ₱50.00\n")
                # Fold
                if order_data['fold']:
                    lines.append("Folding: ₱70.00\n")
                # Detergents
                if orderitem_detergents:
                    for det in orderitem_detergents:
                        lines.append(f"Detergent: {det['DETERGENT_NAME']} (₱{det['UNIT_PRICE']}) x{det['QUANTITY']} = ₱{det['total_price']}\n")
                else:
                    lines.append("Detergent: Own\n")
                # Fabcons
                if orderitem_fabcons:
                    for fab in orderitem_fabcons:
                        lines.append(f"FabCon: {fab['FABCON_NAME']} (₱{fab['UNIT_PRICE']}) x{fab['QUANTITY']} = ₱{fab['total_price']}\n")
                else:
                    lines.append("FabCon: Own\n")
                lines.append("-" * 32 + "\n")
                lines.append(f"Total Price: ₱{order.get('TOTAL_PRICE'):.2f}\n")
                lines.append("\nThank you!\n")

                receipt_text = "".join(lines)
                p.text(receipt_text)

                # Print QR code if available
                if qr_code_path:
                    qr_full_path = os.path.join(app.static_folder, qr_code_path)
                    if os.path.exists(qr_full_path):
                        p.image(qr_full_path)
                        p.text("\n")  # Space after QR

                p.cut()
            except Exception as e:
                print("Printer error:", e)
        
        # Clear session data after successful order creation
        session.pop('customer_data', None)
        session.pop('order_data', None)
        session.pop('total_weight', None)
        session.pop('total_load', None)
        session.pop('order_type', None)
        
        flash('Order confirmed successfully!')
        return redirect(url_for('home'))
    
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
    order = {
        'ORDER_ID': 'Pending',  # Will be assigned when saved
        'ORDER_TYPE': order_data['order_type'],
        'ORDER_STATUS': 'Pending',
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
    
    # Calculate load price
    load_price = order_data['total_load'] * 50.00
    
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
    
    # Separate orders into priority orders (drop-off) and self-service orders
    priority_orders = [o for o in orders_with_details if o.get('ORDER_TYPE', '').lower() == 'drop-off']
    self_service_orders = [o for o in orders_with_details if o.get('ORDER_TYPE', '').lower() == 'self-service']
    
    # Limit to 5 most recent for each section
    priority_orders = priority_orders[:5]
    self_service_orders = self_service_orders[:5]
    
    # Calculate statistics
    total_orders = len(orders_with_details)
    self_service_count = len([o for o in orders_with_details if o.get('ORDER_TYPE', '').lower() == 'self-service'])
    drop_off_count = len([o for o in orders_with_details if o.get('ORDER_TYPE', '').lower() == 'drop-off'])
    
    pending_count = len([o for o in orders_with_details if (o.get('ORDER_STATUS') or '').lower() == 'pending'])
    pickup_count = len([o for o in orders_with_details if (o.get('ORDER_STATUS') or '').lower() == 'pickup'])
    completed_count = len([o for o in orders_with_details if (o.get('ORDER_STATUS') or '').lower() == 'completed'])

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
        completed_count=completed_count
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
    
    # Get statistics
    stats = get_customer_statistics()
    
    # Filter by search query if provided
    search_query = request.args.get('q', '').strip().lower()
    if search_query:
        customers_data = [c for c in customers_data if 
            search_query in str(c['CUSTOMER_ID']).lower() or
            search_query in c['FULLNAME'].lower() or
            (c['PHONE_NUMBER'] and search_query in c['PHONE_NUMBER'].lower())]
    
    # Filter by payment status if provided
    payment_status = request.args.get('payment_status')
    if payment_status:
        customers_data = [c for c in customers_data if c['PAYMENT_STATUS'].lower() == payment_status.lower()]
    
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

    # Always update order status to "Pick-up" after QR scan
    dbhelper.db.collection('ORDER').document(
        dbhelper.db.collection('ORDER').where('ORDER_ID', '==', order_id).limit(1).get()[0].id
    ).update({'ORDER_STATUS': 'Pick-up', 'DATE_UPDATED': datetime.now()})
    order['ORDER_STATUS'] = 'Pick-up'

    customer = dbhelper.get_customer_by_id(order['CUSTOMER_ID']) if order.get('CUSTOMER_ID') else None
    orderitem = dbhelper.get_orderitem_by_id(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else None

    detergents = dbhelper.get_orderitem_detergents(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else []
    fabcons = dbhelper.get_orderitem_fabcons(order['ORDERITEM_ID']) if order.get('ORDERITEM_ID') else []

    # Calculate total price breakdown
    total_price = 0.0
    breakdown = {}

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
        load_price = float(order['TOTAL_LOAD']) * 50.0
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
        orderitems_map[oid] = dbhelper.get_orderitem_by_id(oid)
    
    # Attach orderitem data to each order
    for order in paginated_orders:
        order['orderitem_data'] = orderitems_map.get(order.get('ORDERITEM_ID'))

    return render_template('admin_order_report.html',
                           paginated_orders=paginated_orders,
                           total_orders=total_orders,
                           total_revenue=round(total_revenue, 2),
                           pending_count=len(pending_orders),
                           completed_count=len(completed_orders),
                           page=page,
                           total_pages=total_pages,
                           dbhelper=dbhelper
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
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    # Always get the full lists for summary cards
    all_detergents = get_all_detergents()
    all_fabric_conditioners = get_all_fabric_conditioners()
    
    # Initialize filtered data
    detergents = []
    fabric_conditioners = []
    
    # Get filtered data based on inventory type and search query
    if inv_type == 'detergent':
        if search_query:
            detergents = search_detergents(search_query)
        else:
            detergents = all_detergents.copy()
        fabric_conditioners = []
    elif inv_type == 'fabcon':
        if search_query:
            fabric_conditioners = search_fabric_conditioners(search_query)
        else:
            fabric_conditioners = all_fabric_conditioners.copy()
        detergents = []
    
    # Apply date filtering if dates are provided
    if start_date or end_date:
        # Convert string dates to datetime objects
        start_date_obj = None
        end_date_obj = None
        
        if start_date:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
        if end_date:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
        
        # Filter detergents by date
        if inv_type == 'detergent':
            filtered_detergents = []
            for item in detergents:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_detergents.append(item)
            detergents = filtered_detergents
        # Filter fabric conditioners by date
        elif inv_type == 'fabcon':
            filtered_fabcons = []
            for item in fabric_conditioners:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_fabcons.append(item)
            fabric_conditioners = filtered_fabcons
    elif inv_type == 'both':
        # For both, combine and filter by date
        combined_inventory = all_detergents + all_fabric_conditioners
        filtered_combined = []
        for item in combined_inventory:
            item_date = item['DATE_CREATED']
            if not isinstance(item_date, datetime):
                item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
            if (not start_date_obj or item_date >= start_date_obj) and \
               (not end_date_obj or item_date <= end_date_obj):
                filtered_combined.append(item)
        detergents = filtered_combined
        fabric_conditioners = filtered_combined
    
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

    return render_template(
        'admin_inventory_report.html',
        all_detergents=all_detergents,
        all_fabric_conditioners=all_fabric_conditioners,
        detergents=paginated_detergents,
        fabric_conditioners=paginated_fabcons,
        current_page=page,
        total_pages=total_pages
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

    # Convert to DataFrame
    df = pd.DataFrame(filtered_orders)
    # Remove columns not needed (e.g., images, etc.)
    for col in ['IMAGE_FILENAME', 'QR_CODE']:
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
    if format == 'excel':
        output = io.BytesIO()
        df = make_excel_safe(df)
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
        output.seek(0)
        return send_file(output, download_name=f"{filename}.xlsx", as_attachment=True)
    elif format == 'csv':
        output = io.StringIO()
        df = make_excel_safe(df)
        df.to_csv(output, index=False)
        output.seek(0)
        return Response(output.getvalue(), mimetype='text/csv', headers={"Content-Disposition": f"attachment;filename={filename}.csv"})
    elif format == 'pdf':
        # Styled PDF export (same as inventory/customer report)
        from fpdf import FPDF
        pdf = FPDF(orientation='L', unit='mm', format='legal')  # <-- use legal size for long bondpaper
        pdf.set_auto_page_break(auto=True, margin=15)
        def add_title_bar(title):
            pdf.set_fill_color(18, 45, 105)  # #122D69
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
            # Decrease header font size here
            pdf.set_font('Arial', 'B', 7)  # <-- changed from 8 to 7
            pdf.set_fill_color(245, 247, 250)  # #f5f7fa
            pdf.set_text_color(35, 56, 114)    # #233872
            available_width = pdf.w - 2 * pdf.l_margin
            columns = list(df.columns)
            # Assign custom widths: wider for name/value, narrower for ID/dates
            col_widths = []
            for col in columns:
                if 'NAME' in col or 'Value' in col:
                    col_widths.append(available_width * 0.18)
                elif 'ID' in col:
                    col_widths.append(available_width * 0.10)
                elif 'DATE' in col:
                    col_widths.append(available_width * 0.18)
                else:
                    col_widths.append(available_width * 0.12)
            total_width = sum(col_widths)
            if total_width > available_width:
                col_widths = [w * available_width / total_width for w in col_widths]
            # Header
            for i, col in enumerate(columns):
                pdf.cell(col_widths[i], 7, str(col), border=1, align='C', fill=True)
            pdf.ln()
            # Table rows
            pdf.set_font('Arial', '', 9)
            for row_idx, row in df.iterrows():
                if row_idx % 2 == 0:
                    pdf.set_fill_color(248, 250, 252)  # #f8fafc
                else:
                    pdf.set_fill_color(255, 255, 255)  # white
                pdf.set_text_color(0, 0, 0)
                for i, item in enumerate(row):
                    pdf.cell(col_widths[i], 7, str(item), border=1, align='C', fill=True)
                pdf.ln()
        pdf.add_page()
        add_title_bar('Order Report')
        # Optionally show date range if filtered
        if start_date or end_date:
            pdf.set_font('Arial', '', 10)
            pdf.set_text_color(0, 0, 0)
            date_range = "Date Range: "
            if start_date:
                date_range += f"From {start_date} "
            if end_date:
                date_range += f"To {end_date}"
            pdf.cell(0, 7, date_range, ln=True, align='L')
            pdf.ln(2)
        # Prepare DataFrame for table
        df = df.copy()
        # Optionally reorder columns for better layout
        preferred_cols = [
            'ORDER_ID', 'CUSTOMER_ID', 'CUSTOMER_NAME', 'ORDER_TYPE', 'PRIORITY',
            'PAYMENT_STATUS', 'ORDER_STATUS', 'DATE_CREATED', 'DATE_UPDATED', 'TOTAL_LOAD', 'TOTAL_PRICE', 'PICKUP_SCHEDULE'
        ]
        df = df[[col for col in preferred_cols if col in df.columns] + [col for col in df.columns if col not in preferred_cols]]
        add_table(df)
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
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    # Get data based on inventory type
    if inv_type == 'detergent':
        if search_query:
            data = search_detergents(search_query)
        else:
            data = get_all_detergents()
        # Add Total Value column
        for item in data:
            item['Total_Value'] = item['DETERGENT_PRICE'] * item['QTY']
        sheet_name = 'Detergents'
        filename = 'detergent_inventory_report'
    elif inv_type == 'fabcon':
        if search_query:
            data = search_fabric_conditioners(search_query)
        else:
            data = get_all_fabric_conditioners()
        # Add Total Value column
        for item in data:
            item['Total_Value'] = item['FABCON_PRICE'] * item['QTY']
        sheet_name = 'Fabric Conditioners'
        filename = 'fabcon_inventory_report'
    else:
        # Get both detergent and fabric conditioner data
        if search_query:
            det_data = search_detergents(search_query)
            fabcon_data = search_fabric_conditioners(search_query)
        else:
            det_data = get_all_detergents()
            fabcon_data = get_all_fabric_conditioners()
        
        # Add Total Value column to detergents
        for item in det_data:
            item['Total_Value'] = item['DETERGENT_PRICE'] * item['QTY']
        
        # Add Total Value column to fabric conditioners
        for item in fabcon_data:
            item['Total_Value'] = item['FABCON_PRICE'] * item['QTY']
        
        filename = 'inventory_report'
    
    # Apply date filtering if dates are provided
    if start_date or end_date:
        # Convert string dates to datetime objects
        start_date_obj = None
        end_date_obj = None
        
        if start_date:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
        if end_date:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
        
        # Filter data by date
        if inv_type == 'detergent':
            filtered_detergents = []
            for item in data:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_detergents.append(item)
            data = filtered_detergents
        elif inv_type == 'fabcon':
            filtered_fabcons = []
            for item in data:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
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
                    item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_det_data.append(item)
            det_data = filtered_det_data
            
            # Filter fabric conditioner data
            filtered_fabcon_data = []
            for item in fabcon_data:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_fabcon_data.append(item)
            fabcon_data = filtered_fabcon_data
    
    # Create DataFrames
    if inv_type in ['detergent', 'fabcon']:
        df = pd.DataFrame(data)
        if 'IMAGE_FILENAME' in df.columns:
            df = df.drop(columns=['IMAGE_FILENAME'])
    else:
        det_df = pd.DataFrame(det_data)
        fabcon_df = pd.DataFrame(fabcon_data)
        if 'IMAGE_FILENAME' in det_df.columns:
            det_df = det_df.drop(columns=['IMAGE_FILENAME'])
        if 'IMAGE_FILENAME' in fabcon_df.columns:
            fabcon_df = fabcon_df.drop(columns=['IMAGE_FILENAME'])

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

        if inv_type in ['detergent', 'fabcon']:
            df = make_excel_safe(df)
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        else:
            det_df = make_excel_safe(det_df)
            fabcon_df = make_excel_safe(fabcon_df)
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                det_df.to_excel(writer, sheet_name='Detergents', index=False)
                fabcon_df.to_excel(writer, sheet_name='Fabric Conditioners', index=False)
        output.seek(0)
        return send_file(output, download_name=f"{filename}.xlsx", as_attachment=True)
    elif format == 'pdf':
        pdf = FPDF(orientation='L', unit='mm', format='legal')
        pdf.set_auto_page_break(auto=True, margin=15)
        def add_title_bar(title):
            pdf.set_fill_color(18, 45, 105)  # #122D69
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
            # Table header
            pdf.set_font('Arial', 'B', 8)
            pdf.set_fill_color(245, 247, 250)  # #f5f7fa
            pdf.set_text_color(35, 56, 114)    # #233872
            # Calculate column widths
            available_width = pdf.w - 2 * pdf.l_margin
            columns = list(df.columns)
            # Assign custom widths: wider for name/value, narrower for ID/dates
            col_widths = []
            for col in columns:
                if 'NAME' in col or 'Value' in col:
                    col_widths.append(available_width * 0.18)
                elif 'ID' in col:
                    col_widths.append(available_width * 0.10)
                elif 'DATE' in col:
                    col_widths.append(available_width * 0.18)
                else:
                    col_widths.append(available_width * 0.12)
            # Normalize if sum > available_width
            total_width = sum(col_widths)
            if total_width > available_width:
                col_widths = [w * available_width / total_width for w in col_widths]
            # Header
            for i, col in enumerate(columns):
                pdf.cell(col_widths[i], 7, str(col), border=1, align='C', fill=True)
            pdf.ln()
            # Table rows
            pdf.set_font('Arial', '', 9)
            for row_idx, row in df.iterrows():
                if row_idx % 2 == 0:
                    pdf.set_fill_color(248, 250, 252)  # #f8fafc
                else:
                    pdf.set_fill_color(255, 255, 255)  # white
                pdf.set_text_color(0, 0, 0)
                for i, item in enumerate(row):
                    pdf.cell(col_widths[i], 7, str(item), border=1, align='C', fill=True)
                pdf.ln()

        if inv_type == 'detergent':
            pdf.add_page()
            add_title_bar('Detergent Inventory')
            add_table(df)
        elif inv_type == 'fabcon':
            pdf.add_page()
            add_title_bar('Fabric Conditioner Inventory')
            add_table(df)
        else:
            pdf.add_page()
            add_title_bar('Detergent Inventory')
            add_table(det_df)
            pdf.add_page()
            add_title_bar('Fabric Conditioner Inventory')
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
    
    # Apply date filtering
    if date_from or date_to:
        filtered_customers = []
        for customer in customers:
            include = True
            if date_from and customer['DATE_CREATED']:
                from_date = datetime.strptime(date_from, '%Y-%m-%d')
                if customer['DATE_CREATED'] < from_date:
                    include = False
            if date_to and customer['DATE_CREATED']:
                to_date = datetime.strptime(date_to, '%Y-%m-%d')
                to_date = to_date.replace(hour=23, minute=59, second=59)
                if customer['DATE_CREATED'] > to_date:
                    include = False
            if include:
                filtered_customers.append(customer)
        customers = filtered_customers
    total_customers = len(customers)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    def make_naive(dt):
        if dt is None:
            return None
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    new_customers_list = [
        c for c in customers
        if c['DATE_CREATED'] and make_naive(c['DATE_CREATED']) >= make_naive(thirty_days_ago)
    ]
    new_customers = len(new_customers_list)
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
                          new_customers_count=new_customers,
                          total_orders=total_orders,
                          customer_monthly_growth=monthly_growth,  # <-- changed variable name
                          current_page=page,
                          total_pages=total_pages)

@app.route('/download_customer_report/<format>')
def download_customer_report(format):
    # Check if user is admin
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
        
    customer_type = request.args.get('type', 'all')
    search_query = request.args.get('q', '').strip()
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    # Get all customers with stats (batch)
    customers = dbhelper.get_all_customers_with_order_stats()
    
    # Apply search filter
    if search_query:
        customers = [c for c in customers if search_query.lower() in c['FULLNAME'].lower() or 
                     search_query in str(c['CUSTOMER_ID']) or 
                     (c['PHONE_NUMBER'] and search_query in c['PHONE_NUMBER'])]
    
    # Apply date filtering
    if date_from or date_to:
        filtered_customers = []
        for customer in customers:
            include = True
            if date_from and customer['DATE_CREATED']:
                from_date = datetime.strptime(date_from, '%Y-%m-%d')
                if customer['DATE_CREATED'] < from_date:
                    include = False
            if date_to and customer['DATE_CREATED']:
                to_date = datetime.strptime(date_to, '%Y-%m-%d')
                to_date = to_date.replace(hour=23, minute=59, second=59)
                if customer['DATE_CREATED'] > to_date:
                    include = False
            if include:
                filtered_customers.append(customer)
        customers = filtered_customers
    thirty_days_ago = datetime.now() - timedelta(days=30)
    def make_naive(dt):
        if dt is None:
            return None
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
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
        for customer in customers_to_display:
            data.append({
                'ID': customer['CUSTOMER_ID'],
                'Full Name': customer['FULLNAME'],
                'Phone Number': customer['PHONE_NUMBER'] or 'N/A',
                'Date Created': customer['DATE_CREATED'].strftime('%Y-%m-%d') if customer['DATE_CREATED'] else 'N/A',
                'Order ID': customer.get('ORDER_ID', 'N/A'),
                'Status': customer.get('ORDER_STATUS', 'N/A'),
                'Payment Status': customer.get('PAYMENT_STATUS', 'N/A')
            })
        
        df = pd.DataFrame(data)
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
            worksheet.set_column('B:B', 20)  # Full Name
            worksheet.set_column('C:C', 15)  # Phone Number
            worksheet.set_column('D:D', 15)  # Date Created
            worksheet.set_column('E:E', 10)  # Order ID
            worksheet.set_column('F:F', 15)  # Status
            worksheet.set_column('G:G', 15)  # Payment Status
            
        output.seek(0)
        return send_file(output, download_name=f"{filename}.xlsx", as_attachment=True)
    
    elif format == 'pdf':
        pdf = FPDF(orientation='L', unit='mm', format='legal')
        pdf.set_auto_page_break(auto=True, margin=15)
        
        def add_title_bar(title):
            pdf.set_fill_color(18, 45, 105)  # #122D69
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
                
            pdf.set_font('Arial', 'B', 8)
            pdf.set_fill_color(245, 247, 250)  # #f5f7fa
            pdf.set_text_color(35, 56, 114)    # #233872
            
            available_width = pdf.w - 2 * pdf.l_margin
            columns = ['ID', 'Full Name', 'Phone Number', 'Date Created', 'Order ID', 'Status', 'Payment Status']
            
            col_widths = [
                available_width * 0.10,  # ID
                available_width * 0.20,  # Full Name
                available_width * 0.15,  # Phone Number
                available_width * 0.15,  # Date Created
                available_width * 0.15,  # Order ID
                available_width * 0.12,  # Status
                available_width * 0.13   # Payment Status
            ]
            
            # Header
            for i, col in enumerate(columns):
                pdf.cell(col_widths[i], 7, str(col), border=1, align='C', fill=True)
            pdf.ln()
            
            pdf.set_font('Arial', '', 9)
            for row_idx, customer in df.iterrows():
                if row_idx % 2 == 0:
                    pdf.set_fill_color(248, 250, 252)  # #f8fafc
                else:
                    pdf.set_fill_color(255, 255, 255)  # white
                pdf.set_text_color(0, 0, 0)
                
                date_created = customer['DATE_CREATED'].strftime('%Y-%m-%d') if customer['DATE_CREATED'] else 'N/A'
                
                pdf.cell(col_widths[0], 7, str(customer['CUSTOMER_ID']), border=1, align='C', fill=True)
                pdf.cell(col_widths[1], 7, customer['FULLNAME'], border=1, align='C', fill=True)
                pdf.cell(col_widths[2], 7, customer['PHONE_NUMBER'] or 'N/A', border=1, align='C', fill=True)
                pdf.cell(col_widths[3], 7, date_created, border=1, align='C', fill=True)
                pdf.cell(col_widths[4], 7, str(customer.get('ORDER_ID', 'N/A')), border=1, align='C', fill=True)
                pdf.cell(col_widths[5], 7, customer.get('ORDER_STATUS', 'N/A'), border=1, align='C', fill=True)
                pdf.cell(col_widths[6], 7, customer.get('PAYMENT_STATUS', 'N/A'), border=1, align='C', fill=True)
                pdf.ln()

        # Create DataFrame
        data = []
        for customer in customers_to_display:
            data.append({
                'ID': customer['CUSTOMER_ID'],
                'Full Name': customer['FULLNAME'],
                'Phone Number': customer['PHONE_NUMBER'] or 'N/A',
                'Date Created': customer['DATE_CREATED'].strftime('%Y-%m-%d') if customer['DATE_CREATED'] else 'N/A',
                'Order ID': customer.get('ORDER_ID', 'N/A'),
                'Status': customer.get('ORDER_STATUS', 'N/A'),
                'Payment Status': customer.get('PAYMENT_STATUS', 'N/A')
            })
        df = pd.DataFrame(data)
        
        pdf.add_page()
        add_title_bar(f"{sheet_name} Report")
        
        if date_from or date_to:
            pdf.set_font('Arial', '', 10)
            pdf.set_text_color(0, 0, 0)
            date_range = "Date Range: "
            if date_from:
                date_range += f"From {date_from} "
            if date_to:
                date_range += f"To {date_to}"
            pdf.cell(0, 7, date_range, ln=True, align='L')
            pdf.ln(2)
        
        add_table(df)
        
        output = io.BytesIO(pdf.output(dest='S').encode('latin1'))
        output.seek(0)
        return send_file(output, download_name=f"{filename}.pdf", as_attachment=True)
    
    elif format == 'csv':
        output = io.StringIO()
        
        data = []
        for customer in customers_to_display:
            data.append({
                'ID': customer['CUSTOMER_ID'],
                'Full Name': customer['FULLNAME'],
                'Phone Number': customer['PHONE_NUMBER'] or 'N/A',
                'Date Created': customer['DATE_CREATED'].strftime('%Y-%m-%d') if customer['DATE_CREATED'] else 'N/A',
                'Order ID': customer.get('ORDER_ID', 'N/A'),
                'Status': customer.get('ORDER_STATUS', 'N/A'),
                'Payment Status': customer.get('PAYMENT_STATUS', 'N/A')
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

# INCOME STATEMENT
@app.route('/income_statement', methods=['GET'])
def income_statement():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
    
    # Get filter parameters
    view = request.args.get('view', 'weekly')
    customer_id = request.args.get('customer_id', type=int)
    tax_rate = float(request.args.get('tax_rate', 0.12))
    selected_month = request.args.get('month', '')  # Format: YYYY-MM
    
    # Pagination parameters
    customer_page = request.args.get('customer_page', 1, type=int)
    order_page = request.args.get('order_page', 1, type=int)
    per_page = 15  # 15 items per page (between 10-20)
    
    # Expense inputs
    detergents_consumables = float(request.args.get('detergents_consumables', 0.0))
    utilities_direct = float(request.args.get('utilities_direct', 0.0))
    salaries_wages = float(request.args.get('salaries_wages', 0.0))
    rent_utilities = float(request.args.get('rent_utilities', 0.0))
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
    if view == 'weekly':
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
            if view == 'monthly' and selected_month:
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
            if view == 'monthly' and selected_month:
                # For monthly with specific month, check if order is within that month
                in_range = start_date_naive <= order_datetime <= end_date_naive
            else:
                # For other views, check if order is after start date
                in_range = order_date_only >= start_date_only
            
            if in_range:
                # Only include completed orders
                order_status = (order.get('ORDER_STATUS') or '').lower()
                if order_status == 'completed':
                    # Check customer filter
                    if customer_id is None or order.get('CUSTOMER_ID') == customer_id:
                        filtered_orders.append(order)
    
    # Calculate metrics
    total_transactions = len(filtered_orders)
    total_sales = sum(float(o.get('TOTAL_PRICE', 0) or 0) for o in filtered_orders)
    
    # Calculate service sales (from orders with ORDER_TYPE)
    service_sales = 0.0
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
            price = float(order.get('TOTAL_PRICE', 0) or 0)
            service_sales += price
        
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
        sorted_detergents = sorted(detergent_counts.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_detergents) > 0:
            best_selling_detergent = sorted_detergents[0][0]
        if len(sorted_detergents) > 1:
            sorted_detergents_asc = sorted(detergent_counts.items(), key=lambda x: x[1], reverse=False)
            slowest_selling_detergent = sorted_detergents_asc[0][0]
    
    # Determine best and slowest selling fabric conditioners
    best_selling_fabcon = 'N/A'
    slowest_selling_fabcon = 'N/A'
    if fabcon_counts:
        sorted_fabcons = sorted(fabcon_counts.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_fabcons) > 0:
            best_selling_fabcon = sorted_fabcons[0][0]
        if len(sorted_fabcons) > 1:
            sorted_fabcons_asc = sorted(fabcon_counts.items(), key=lambda x: x[1], reverse=False)
            slowest_selling_fabcon = sorted_fabcons_asc[0][0]
    
    net_sales = service_sales + other_sales
    
    # Calculate expenses
    total_cogs = detergents_consumables + utilities_direct
    total_opex = salaries_wages + rent_utilities + maintenance_repairs
    gross_profit = net_sales - total_cogs
    operating_income = gross_profit - total_opex
    income_before_tax = operating_income
    income_tax_amount = income_before_tax * tax_rate if income_before_tax > 0 else 0
    net_income = income_before_tax - income_tax_amount
    
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
    
    # Orders breakdown - prepare all orders (without customer names)
    all_orders_breakdown = []
    for order in filtered_orders:
        all_orders_breakdown.append({
            'ORDER_ID': order.get('ORDER_ID'),
            'CUSTOMER_ID': order.get('CUSTOMER_ID'),
            'Revenue': float(order.get('TOTAL_PRICE', 0) or 0),
            'COGS': float(order.get('TOTAL_PRICE', 0) or 0) * 0.3,
            'Net': float(order.get('TOTAL_PRICE', 0) or 0) * 0.7
        })
    
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
        customer_id=customer_id,
        customers=customers,
        tax_rate=tax_rate,
        max=max,
        detergents_consumables=detergents_consumables,
        utilities_direct=utilities_direct,
        salaries_wages=salaries_wages,
        rent_utilities=rent_utilities,
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
        income_tax_amount=income_tax_amount,
        net_income=net_income,
        total_transactions=total_transactions,
        best_selling_service=best_selling_service,
        customers_breakdown=customers_breakdown,
        all_customers_breakdown=all_customers_breakdown,  # For modals
        orders_breakdown=orders_breakdown,
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
    view = request.args.get('view', 'weekly')
    customer_id = request.args.get('customer_id', type=int)
    tax_rate = float(request.args.get('tax_rate', 0.12))
    selected_month = request.args.get('month', '')
    
    # Expense inputs
    detergents_consumables = float(request.args.get('detergents_consumables', 0.0))
    utilities_direct = float(request.args.get('utilities_direct', 0.0))
    salaries_wages = float(request.args.get('salaries_wages', 0.0))
    rent_utilities = float(request.args.get('rent_utilities', 0.0))
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
    if view == 'weekly':
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
            if view == 'monthly' and selected_month:
                in_range = start_date_naive <= order_datetime <= end_date_naive
            else:
                in_range = order_date_only >= start_date_only
            
            if in_range:
                order_status = (order.get('ORDER_STATUS') or '').lower()
                if order_status == 'completed':
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
            if view == 'monthly' and selected_month:
                in_range = start_date_naive <= order_datetime <= end_date_naive
            else:
                in_range = order_date_only >= start_date_only
            
            if in_range:
                if customer_id is None or order.get('CUSTOMER_ID') == customer_id:
                    all_orders_for_report.append(order)
    
    total_orders_count = len(all_orders_for_report)
    
    # Calculate expenses
    total_cogs = detergents_consumables + utilities_direct
    total_opex = salaries_wages + rent_utilities + maintenance_repairs
    net_sales = total_sales
    gross_profit = net_sales - total_cogs
    operating_income = gross_profit - total_opex
    income_before_tax = operating_income
    income_tax_amount = income_before_tax * tax_rate if income_before_tax > 0 else 0
    net_income = income_before_tax - income_tax_amount
    
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
            df.to_excel(writer, sheet_name='Income Statement', index=False)
        output.seek(0)
        return send_file(output, download_name=f"{filename}.xlsx", as_attachment=True)
    elif format == 'csv':
        output = io.StringIO()
        df.to_csv(output, index=False)
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
        
        pdf.add_page()
        add_title_bar('Income Statement Report')
        pdf.set_font('Arial', '', 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 7, f"Period: {period_label}", ln=True, align='L')
        pdf.ln(2)
        add_table(df)
        
        output = io.BytesIO(pdf.output(dest='S').encode('latin1'))
        output.seek(0)
        return send_file(output, download_name=f"{filename}.pdf", as_attachment=True)
    else:
        return "Invalid format", 400

# Store latest weight in a global variable
latest_weight = 0.0

@app.route('/api/weight', methods=['POST'])
def api_weight():
    global latest_weight
    data = request.get_json()
    try:
        # Weight is now sent in kilograms from ESP32
        latest_weight = float(data.get('weight', 0.0))
    except Exception:
        latest_weight = 0.0
    return jsonify({"status": "ok"})

@app.route('/get_latest_weight')
def get_latest_weight():
    global latest_weight
    return jsonify({"weight": latest_weight})

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
        esp32_ip = os.getenv('ESP32_IP', '192.168.109.199')  # <-- Update default IP here
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

@app.route('/api/complete_pickup/<int:order_id>', methods=['POST'])
def api_complete_pickup(order_id):
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return jsonify({'status': 'error', 'msg': 'Unauthorized'}), 401
    # Update order status to Completed
    docs = dbheldb.collection('ORDER').where('ORDER_ID', '==', order_id).limit(1).get()
    if not docs:
        return jsonify({'status': 'error', 'msg': 'Order not found'}), 404
    dbhelper.db.collection('ORDER').document(docs[0].id).update({
        'ORDER_STATUS': 'Completed',
        'DATE_UPDATED': datetime.now()
    })
    return jsonify({'status': 'success'})




    
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')