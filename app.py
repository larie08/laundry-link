from flask import Flask, render_template, request, redirect, url_for
import os
from werkzeug.utils import secure_filename
from dbhelper import *


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/service_type')
def service_type():
    return render_template('service.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/weight_laundry', methods=['GET'])
def weight_laundry():
    return render_template('weight.html')

@app.route('/other_services')
def other_services():
    return render_template('others.html')

@app.route('/payment')
def payment():
    return render_template('payment.html')

# STAFF DETERGENT INVENTORY
@app.route('/detergent_inventory', methods=['GET', 'POST'])
def detergent_inventory():
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
    
    return render_template('staff_detergent_inventory.html', 
                         detergents=detergents,
                         low_stock_detergents=low_stock_detergents,
                         total_items=total_items,
                         low_stock_count=low_stock_count,
                         out_of_stock_count=out_of_stock_count,
                         total_value=total_value)

# STAFF FABRIC CONDITIONER
@app.route('/fabric_conditioner', methods=['GET', 'POST'])
def fabric_conditioner():
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
    
    return render_template(
        'staff_fabric_conditioner.html',
        fabric_conditioners=fabric_conditioners,
        total_items=total_items,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count,
        total_value=total_value
    )

# SCANNER
@app.route('/scanner')
def scanner():
    return render_template('staff_scanner.html') 

if __name__ == '__main__':
    app.run(debug=True)
