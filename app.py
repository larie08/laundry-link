from flask import Flask, render_template

app = Flask(__name__)

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

if __name__ == '__main__':
    app.run(debug=True)
