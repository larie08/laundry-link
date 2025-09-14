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

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.secret_key = 'laundrylink'

# CUSTOMER ROUTES
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/service_type')
def service_type():
    return render_template('service.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        fullname = request.form['name']
        phone_number = request.form['contact']
        
        success = dbhelper.add_customer(fullname, phone_number)
        
        if success:
            flash('Customer added successfully!')
            return redirect(url_for('weight_laundry'))  # go to next step
        else:
            flash('An error occurred. Please try again.')
            return redirect(url_for('contact'))

    return render_template('contact.html')

@app.route('/weight_laundry', methods=['GET'])
def weight_laundry():
    return render_template('weight.html')

@app.route('/other_services')
def other_services():
    detergents = get_all_detergents()
    fabric_conditioners = get_all_fabric_conditioners()
    return render_template('others.html', detergents=detergents, fabric_conditioners=fabric_conditioners)

@app.route('/submit_others', methods=['POST'])
def submit_others():
    # Get form data
    detergent_ids = request.form.getlist('detergent_ids')
    fabcon_ids = request.form.getlist('fabcon_ids')
    own_detergent = request.form.get('own_detergent') == '1'
    own_fabcon = request.form.get('own_fabcon') == '1'
    iron = request.form.get('iron') == '1'
    fold = request.form.get('fold') == '1'
    priority = request.form.get('priority') == '1'
    
    # Get pickup schedule and notes data
    pickup_date = request.form.get('pickup_date')
    pickup_time = request.form.get('pickup_time')
    order_note = request.form.get('order_note')
    
    # Combine date and time into a single datetime string if both are provided
    pickup_schedule = None
    if pickup_date and pickup_time:
        pickup_schedule = f"{pickup_date} {pickup_time}"
    elif pickup_date:
        pickup_schedule = f"{pickup_date} 00:00"
    
    # Insert into ORDER_ITEM with pickup_schedule and order_note
    orderitem_id = add_order_item(own_detergent, own_fabcon, iron, fold, priority, pickup_schedule, order_note)

    # Only insert into ORDERITEM_DETERGENT if not own detergent
    if not own_detergent:
        for det_id in detergent_ids:
            qty = int(request.form.get(f'detergent_qty_{det_id}', 1))
            price = float(request.form.get(f'detergent_price_{det_id}', 0))
            add_orderitem_detergent(orderitem_id, int(det_id), qty, price)

    # Only insert into ORDERITEM_FABCON if not own fabcon
    if not own_fabcon:
        for fab_id in fabcon_ids:
            qty = int(request.form.get(f'fabcon_qty_{fab_id}', 1))
            price = float(request.form.get(f'fabcon_price_{fab_id}', 0))
            add_orderitem_fabcon(orderitem_id, int(fab_id), qty, price)

    return redirect(url_for('payments'))

@app.route('/payments')
def payments():
    return render_template('payments.html')





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

    # BASED ON ROLE
    template_name = 'admin_dashboard.html' if session['role'] == 'admin' else 'staff_dashboard.html'

    return render_template(template_name,
        low_detergents=low_detergents,
        low_fabcons=low_fabcons
    )

# ADMIN AND STAFF
@app.route('/detergent_inventory', methods=['GET', 'POST'])
def detergent_inventory():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        action = request.form.get('action', 'Add')

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
                add_detergent(name, price, quantity, filename)
            elif action == 'Update':
                detergent_id = int(request.form['detergent_id'])
                if not filename:
                    old = get_detergent_by_id(detergent_id)
                    filename = old['IMAGE_FILENAME'] if old else None
                update_detergent(detergent_id, name, price, quantity, filename)

        elif action == 'Delete':
            detergent_id = int(request.form['detergent_id'])
            delete_detergent(detergent_id)

        return redirect(url_for('detergent_inventory'))

    # SEARCH
    search_query = request.args.get('q', '').strip()
    if search_query:
        detergents = search_detergents(search_query)
    else:
        detergents = get_all_detergents()
    
    # LOW STOCK DETERGENTS
    low_stock_detergents = [d for d in detergents if d['QTY'] <= 10]
    
    # TOTAL DETERGENTS
    total_items = len(detergents)
    low_stock_count = len(low_stock_detergents)
    out_of_stock_count = len([d for d in detergents if d['QTY'] == 0])
    
    # TOTAL INVENTORY VALUE
    total_value = sum(d['DETERGENT_PRICE'] * d['QTY'] for d in detergents)
    
    # BASED ON ROLE
    template_name = 'admin_detergent_inventory.html' if session['role'] == 'admin' else 'staff_detergent_inventory.html'
    
    return render_template(template_name, 
                         detergents=detergents,
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
                add_fabric_conditioner(name, price, quantity, filename)
            elif action == 'Update':
                fabcon_id = int(request.form['fabric_conditioner_id'])
                if not filename:
                    old = get_fabric_conditioner_by_id(fabcon_id)
                    filename = old['IMAGE_FILENAME'] if old else None
                update_fabric_conditioner(fabcon_id, name, price, quantity, filename)

        elif action == 'Delete':
            fabcon_id = int(request.form['fabric_conditioner_id'])
            delete_fabric_conditioner(fabcon_id)

        return redirect(url_for('fabric_conditioner'))

    # SEARCH
    search_query = request.args.get('q', '').strip()
    if search_query:
        fabric_conditioners = search_fabric_conditioners(search_query)
    else:
        fabric_conditioners = get_all_fabric_conditioners()
    
    # Get total inventory value
    total_value = get_fabcon_total_value()['TotalValue']
    
    # Calculate additional statistics
    total_items = len(fabric_conditioners)
    low_stock_count = len([f for f in fabric_conditioners if f['QTY'] <= 10])
    out_of_stock_count = len([f for f in fabric_conditioners if f['QTY'] == 0])
    
    # BASED ON ROLE
    template_name = 'admin_fabric_conditioner.html' if session['role'] == 'admin' else 'staff_fabric_conditioner.html'
    
    return render_template(template_name,
        fabric_conditioners=fabric_conditioners,
        total_items=total_items,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count,
        total_value=total_value
    )

# ADMIN AND STAFF
@app.route('/scanner')
def scanner():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return redirect(url_for('admin_login'))
    
    # BASED ON ROLE
    template_name = 'admin_scanner.html' if session['role'] == 'admin' else 'staff_scanner.html'
    return render_template(template_name)

# ADMIN AND STAFF
@app.route('/customers')
def customers():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return redirect(url_for('admin_login'))
    
    # BASED ON ROLE
    template_name = 'admin_customers.html' if session['role'] == 'admin' else 'staff_customers.html'
    return render_template(template_name)

# ADMIN AND STAFF
@app.route('/orders')
def orders():
    if 'user_id' not in session or session['role'] not in ['admin', 'staff']:
        return redirect(url_for('admin_login'))
    
    # BASED ON ROLE
    template_name = 'admin_order.html' if session['role'] == 'admin' else 'staff_order.html'
    return render_template(template_name)

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
    
    return render_template('admin_order_report.html')

# INVENTORY REPORT
@app.route('/inventory_report')
def inventory_report():
    # CHECK IF ADMIN IS USER 
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
        
    # Get query parameters
    search_query = request.args.get('q', '').strip()
    inv_type = request.args.get('type', 'detergent')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    # Always get the full lists for summary cards
    all_detergents = get_all_detergents()
    all_fabric_conditioners = get_all_fabric_conditioners()
    
    # Initialize filtered data
    detergents = []
    fabric_conditioners = []
    
    # Get filtered data based on inventory type and search query
    if inv_type == 'detergent' or inv_type == None:
        if search_query:
            detergents = search_detergents(search_query)
        else:
            detergents = all_detergents.copy()
        fabric_conditioners = []  # Ensure only one table is filled
    elif inv_type == 'fabcon':
        if search_query:
            fabric_conditioners = search_fabric_conditioners(search_query)
        else:
            fabric_conditioners = all_fabric_conditioners.copy()
        detergents = []  # Ensure only one table is filled
    
    # Apply date filtering if dates are provided
    if start_date or end_date:
        # Convert string dates to datetime objects
        start_date_obj = None
        end_date_obj = None
        
        if start_date:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
        if end_date:
            # Set end_date to end of day
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
        
        # Filter detergents by date
        if inv_type == 'detergent' or inv_type == None:
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
    
    # If no type is specified, get both for initial page load
    if inv_type == None:
        fabric_conditioners = all_fabric_conditioners.copy()
    
    return render_template(
        'admin_inventory_report.html',
        all_detergents=all_detergents,
        all_fabric_conditioners=all_fabric_conditioners,
        detergents=detergents,
        fabric_conditioners=fabric_conditioners
    )

# For inventory report downloads
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
            # Set end_date to end of day
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
        
        # Filter data by date
        if inv_type == 'detergent':
            filtered_data = []
            for item in data:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_data.append(item)
            data = filtered_data
        elif inv_type == 'fabcon':
            filtered_data = []
            for item in data:
                item_date = item['DATE_CREATED']
                if not isinstance(item_date, datetime):
                    item_date = datetime.strptime(item_date, '%Y-%m-%d %H:%M:%S')
                if (not start_date_obj or item_date >= start_date_obj) and \
                   (not end_date_obj or item_date <= end_date_obj):
                    filtered_data.append(item)
            data = filtered_data
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
        if inv_type in ['detergent', 'fabcon']:
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        else:
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                det_df.to_excel(writer, sheet_name='Detergents', index=False)
                fabcon_df.to_excel(writer, sheet_name='Fabric Conditioners', index=False)
        output.seek(0)
        return send_file(output, download_name=f"{filename}.xlsx", as_attachment=True)
    elif format == 'pdf':
        pdf = FPDF(orientation='L', unit='mm', format='A4')
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
            for row_idx, (_, row) in enumerate(df.iterrows()):
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
    
    # Get all customers
    customers = dbhelper.get_all_customers()
    
    if search_query:
        customers = [c for c in customers if search_query.lower() in c['FULLNAME'].lower() or 
                     search_query in str(c['CUSTOMER_ID']) or 
                     (c['PHONE_NUMBER'] and search_query in c['PHONE_NUMBER'])]
    
    # Get customer order data
    for customer in customers:
        sql = """
            SELECT TOP 1 ORDER_ID, ORDER_STATUS, PAYMENT_STATUS
            FROM [ORDER] 
            WHERE CUSTOMER_ID = ?
            ORDER BY DATE_CREATED DESC
        """
        result = dbhelper.getallprocess(sql, (customer['CUSTOMER_ID'],))
        if result:
            customer['ORDER_ID'] = result[0]['ORDER_ID']
            customer['ORDER_STATUS'] = result[0]['ORDER_STATUS']
            customer['PAYMENT_STATUS'] = result[0]['PAYMENT_STATUS']
        else:
            customer['ORDER_ID'] = 'N/A'
            customer['ORDER_STATUS'] = 'N/A'
            customer['PAYMENT_STATUS'] = 'N/A'
        
        sql = "SELECT COUNT(*) as total_orders FROM [ORDER] WHERE CUSTOMER_ID = ?"
        count_result = dbhelper.getallprocess(sql, (customer['CUSTOMER_ID'],))
        customer['total_orders'] = count_result[0]['total_orders'] if count_result else 0
    
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
    new_customers_list = [c for c in customers if c['DATE_CREATED'] and c['DATE_CREATED'] >= thirty_days_ago]
    new_customers = len(new_customers_list)
    
    total_orders = sum(c.get('total_orders', 0) for c in customers)
    avg_orders = round(total_orders / total_customers, 2) if total_customers > 0 else 0
    
    return render_template('admin_customer_report.html', 
                          customers=customers,
                          total_customers=total_customers,
                          new_customers_count=new_customers,
                          total_orders=total_orders,
                          avg_orders_per_customer=avg_orders)

@app.route('/download_customer_report/<format>')
def download_customer_report(format):
    # Check if user is admin
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('admin_login'))
        
    customer_type = request.args.get('type', 'all')
    search_query = request.args.get('q', '').strip()
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    # Get all customers
    customers = dbhelper.get_all_customers()
    
    # Apply search filter
    if search_query:
        customers = [c for c in customers if search_query.lower() in c['FULLNAME'].lower() or 
                     search_query in str(c['CUSTOMER_ID']) or 
                     (c['PHONE_NUMBER'] and search_query in c['PHONE_NUMBER'])]
    
    # Get customer order data
    for customer in customers:
        sql = """
            SELECT TOP 1 ORDER_ID, ORDER_STATUS, PAYMENT_STATUS
            FROM [ORDER] 
            WHERE CUSTOMER_ID = ?
            ORDER BY DATE_CREATED ASC
        """
        result = dbhelper.getallprocess(sql, (customer['CUSTOMER_ID'],))
        if result:
            customer['ORDER_ID'] = result[0]['ORDER_ID']
            customer['ORDER_STATUS'] = result[0]['ORDER_STATUS']
            customer['PAYMENT_STATUS'] = result[0]['PAYMENT_STATUS']
        else:
            customer['ORDER_ID'] = 'N/A'
            customer['ORDER_STATUS'] = 'N/A'
            customer['PAYMENT_STATUS'] = 'N/A'
        
        sql = "SELECT COUNT(*) as total_orders FROM [ORDER] WHERE CUSTOMER_ID = ?"
        count_result = dbhelper.getallprocess(sql, (customer['CUSTOMER_ID'],))
        customer['total_orders'] = count_result[0]['total_orders'] if count_result else 0
    
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
    new_customers_list = [c for c in customers if c['DATE_CREATED'] and c['DATE_CREATED'] >= thirty_days_ago]
    
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
        pdf = FPDF(orientation='L', unit='mm', format='A4')
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
            
            for i, col in enumerate(columns):
                pdf.cell(col_widths[i], 7, str(col), border=1, align='C', fill=True)
            pdf.ln()
            
            pdf.set_font('Arial', '', 9)
            for row_idx, customer in enumerate(customers_to_display):
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

if __name__ == '__main__':
    app.run(debug=True)
    