# BISAYA, TAGALOG UG ENGLISH NANING COMMENT PARA MAS MAKASABOT SI OKS OR KITANG TANAN HAHAHHAHAHAHHA 
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# FIRBASE SDK CODE - DAPAT ADMIN ARI
import firebase_admin
from firebase_admin import credentials, firestore

# PLACEHOLDER PALANG NIS FIRESTORE CLIENT (LAZY INITIALIZATION)
db = None

# ARI NA JUD MAGSUGOD A TUNG HELPERS HAHHAHAH
# GLOBAL FIRESTORE CLIENT 
'''
GAGI ING ANI MAN DIAY MAG COMMENT PARA DILI NA MAG TAGSA2x T_T
    === FIREBASE_CREDENTIALS env var
    === GOOGLE_APPLICATION_CREDENTIALS env var
    === serviceAccountKey.json  ===== kani siya kay ako ray mo hatag ani nga file since gikuha ni nako sa akung firebase accountkeys 
    === pero ma change ra jud ni siya depende kang kinsa jung firebase gamiton. - BY ALEXA
'''
# REQURE_DB
def _require_db():
    global db
    if db is not None:
        return
    # INITIALIZATION OF FIREBASE ADMIN
    if not firebase_admin._apps:
        cred_path = os.getenv('FIREBASE_CREDENTIALS') or os.getenv('GOOGLE_APPLICATION_CREDENTIALS') or 'serviceAccountKey.json'
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        else:
            # IF DILI TA MAKA CONNECT SA CLOUD PLWEDE TA MO USE UG EMULATOR WHICH ALLOW US TO USE THE WEBSITE WITHOUT CREDENTIALS
            if os.getenv('FIRESTORE_EMULATOR_HOST'):
                firebase_admin.initialize_app()
            else:
                raise RuntimeError(
                    "Firebase credentials not found. Set FIREBASE_CREDENTIALS or GOOGLE_APPLICATION_CREDENTIALS to your serviceAccountKey.json, or place serviceAccountKey.json in project root."
                )
    # CREATE A CLIENT
    db = firestore.client()

# DEFAULT USERS 
def _ensure_default_users():

    # INITIALIZING THE FIRESTORE CLIENT
    _require_db()

    # REFERENCE TO USER COLLECTION IN THE FIRESTORE - GAMIT NAKO AKUNG ACCOUNT ARI - ALEXA
    users_ref = db.collection('USER')
    # MAO NI TABLE SA FIRESTORE LIKE COLLECTION ANG NAKA BUTANG 

    # ADMIN ACCOUNT
    admin_q = users_ref.where('USERNAME', '==', 'admin').limit(1).get()
    if not admin_q:
        transaction = db.transaction()
        admin_id = _get_next_id(transaction, 'USER_ID')
        users_ref.add({
            'USER_ID': admin_id,
            'USERNAME': 'admin',
            'PASSWORD': 'admin123',
            'ROLE': 'admin',
            'FULLNAME': 'Administrator',
            'DATE_CREATED': _now(),
        })

    # STAFF ACCOUNT
    staff_q = users_ref.where('USERNAME', '==', 'staff').limit(1).get()
    if not staff_q:
        transaction = db.transaction()
        staff_id = _get_next_id(transaction, 'USER_ID')
        users_ref.add({
            'USER_ID': staff_id,
            'USERNAME': 'staff',
            'PASSWORD': 'staff123',
            'ROLE': 'staff',
            'FULLNAME': 'Staff',
            'DATE_CREATED': _now(),
        })

# HELPER FUNCTIONS 
def _now() -> datetime:
    """Return current timestamp as Python datetime (Firestore stores natively)."""
    return datetime.now()

def _get_counter_doc():
    """Return reference to the single counters document we use for IDs."""
    _require_db()
    return db.collection('counters').document('global')

@firestore.transactional
def _get_next_id(transaction: firestore.Transaction, key: str) -> int:
    """Atomically increment and return the next integer for the given key.

    Example keys: CUSTOMER_ID, USER_ID, ORDER_ID, etc.
    """
    counter_ref = _get_counter_doc()
    snapshot = counter_ref.get(transaction=transaction)
    data = snapshot.to_dict() or {}
    next_val = int(data.get(key, 0)) + 1
    transaction.set(counter_ref, {key: next_val}, merge=True)
    return next_val


# MAO NI ANG CODE PAR
# KANI ARI NGA CODE KAY PARA NI DILI MAUSAB ATUNG CODE SA app.py SINCE GI CONVERT MAN NATO ATUNG CODE FROM SQL TO FIREBASE DAPAT JUD USBON TANAN HASTA ANG app.py 
# BUT, SINCE DBHELPER PAMAN ATUNG GI USAB E AS-IS LANG SA NI ARI. 
# TO CONCLUDE, DO NOT CHANGE OR REMOVE THIS!!!!
def _as_sql_row(data: Dict[str, Any]) -> Dict[str, Any]:
    return data

def _ensure_junction_collections():
    """Junction collections are now created, nothing to do."""
    pass

def initialize_database():
    """Initialize Firestore and ensure default users exist."""
    _require_db()
    _ensure_default_users()
    # No need to call _ensure_junction_collections anymore
    print("Firebase initialized and default users ensured.")

def postprocess(sql: str, params: tuple = ()) -> bool:
    """SQL helper kept for backward-compatibility (no-op under Firestore)."""
    print("postprocess not supported under Firestore. Called with:", sql, params)
    return False

def getallprocess(sql: str, params: tuple = ()) -> list:
    """Very small SQL emulation for specific queries used in reports.

    Supported queries:
      - Latest order for a customer (TOP 1 ... ORDER BY DATE_CREATED)
      - Count orders per customer (SELECT COUNT(*))
      - TOP 1 customer by CUSTOMER_ID
    """
    _require_db()
    text = sql.strip().upper()
    if 'FROM [ORDER]' in text and 'WHERE CUSTOMER_ID' in text and 'ORDER BY DATE_CREATED' in text:
        customer_id = params[0]
        direction = 'DESC' if 'DESC' in text else 'ASC'
        orders = db.collection('ORDER').where('CUSTOMER_ID', '==', customer_id).order_by('DATE_CREATED', direction=firestore.Query.DESCENDING if direction == 'DESC' else firestore.Query.ASCENDING).limit(1).get()
        out: List[Dict[str, Any]] = []
        for doc in orders:
            d = doc.to_dict()
            out.append({'ORDER_ID': d.get('ORDER_ID'), 'ORDER_STATUS': d.get('ORDER_STATUS'), 'PAYMENT_STATUS': d.get('PAYMENT_STATUS')})
        return out
    if 'SELECT COUNT(*) AS TOTAL_ORDERS' in text and 'FROM [ORDER]' in text and 'WHERE CUSTOMER_ID' in text:
        customer_id = params[0]
        orders = db.collection('ORDER').where('CUSTOMER_ID', '==', customer_id).get()
        return [{'total_orders': len(orders)}]
    if text.startswith('SELECT TOP 1 * FROM CUSTOMER'):
        docs = db.collection('CUSTOMER').order_by('CUSTOMER_ID', direction=firestore.Query.DESCENDING).limit(1).get()
        return [doc.to_dict() for doc in docs]
    print('getallprocess: unsupported SQL under Firestore:', sql)
    return []

# ==================================================
# CUSTOMER TABLE
# - add_customer(): create new customer
# - get_all_customers(): list customers (ORDER BY FULLNAME)
# - get_customer_by_id(): fetch single customer
# - update_customer(): edit customer info
# - delete_customer(): remove customer
# ==================================================
def add_customer(fullname: str, phone_number: str) -> bool:
    """Create a new customer and assign an incremental CUSTOMER_ID."""
    _require_db()
    transaction = db.transaction()
    customer_id = _get_next_id(transaction, 'CUSTOMER_ID')
    db.collection('CUSTOMER').add({
        'CUSTOMER_ID': customer_id,
        'FULLNAME': fullname,
        'PHONE_NUMBER': phone_number,
        'DATE_CREATED': _now(),
    })
    return True

def get_all_customers() -> list:
    """Return all customers ordered by FULLNAME (like SQL ORDER BY)."""
    _require_db()
    docs = db.collection('CUSTOMER').order_by('FULLNAME').get()
    return [_as_sql_row(doc.to_dict()) for doc in docs]

def get_customer_by_id(customer_id: int) -> dict:
    """Fetch a single customer by CUSTOMER_ID."""
    _require_db()
    docs = db.collection('CUSTOMER').where('CUSTOMER_ID', '==', customer_id).limit(1).get()
    return docs[0].to_dict() if docs else None

def update_customer(customer_id: int, fullname: str, phone_number: str) -> bool:
    """Update FULLNAME and PHONE_NUMBER for a customer."""
    _require_db()
    docs = db.collection('CUSTOMER').where('CUSTOMER_ID', '==', customer_id).limit(1).get()
    if not docs:
        return False
    db.collection('CUSTOMER').document(docs[0].id).update({
        'FULLNAME': fullname,
        'PHONE_NUMBER': phone_number,
    })
    return True

def delete_customer(customer_id: int) -> bool:
    """Delete a customer document by CUSTOMER_ID."""
    _require_db()
    docs = db.collection('CUSTOMER').where('CUSTOMER_ID', '==', customer_id).limit(1).get()
    if not docs:
        return False
    db.collection('CUSTOMER').document(docs[0].id).delete()
    return True

def add_user(username: str, password: str, role: str, fullname: str) -> bool:
    """Create a new user (admin or staff) with incremented USER_ID."""
    _require_db()
    transaction = db.transaction()
    user_id = _get_next_id(transaction, 'USER_ID')
    db.collection('USER').add({
        'USER_ID': user_id,
        'USERNAME': username,
        'PASSWORD': password,
        'ROLE': role,
        'FULLNAME': fullname,
        'DATE_CREATED': _now(),
    })
    return True

# ==================================================
# USER TABLE
# - add_user(): create new user (admin/staff)
# - get_all_users(): list users
# - get_user_by_id(): fetch single user
# - update_user(): edit user info
# - authenticate_user(): login helper
# ==================================================
def get_all_users() -> list:
    """Return all users ordered by FULLNAME."""
    _require_db()
    docs = db.collection('USER').order_by('FULLNAME').get()
    return [doc.to_dict() for doc in docs]

def get_user_by_id(user_id: int) -> dict:
    """Fetch a single user by USER_ID."""
    _require_db()
    docs = db.collection('USER').where('USER_ID', '==', user_id).limit(1).get()
    return docs[0].to_dict() if docs else None

def update_user(user_id: int, username: str, password: str, role: str, fullname: str) -> bool:
    """Update user fields for an existing USER_ID."""
    _require_db()
    docs = db.collection('USER').where('USER_ID', '==', user_id).limit(1).get()
    if not docs:
        return False
    db.collection('USER').document(docs[0].id).update({
        'USERNAME': username,
        'PASSWORD': password,
        'ROLE': role,
        'FULLNAME': fullname,
    })
    return True

def authenticate_user(username: str, password: str) -> dict:
    """Return the user dict if username/password match, else None.

    We also auto-create default users if they don't exist yet (first run).
    """
    _require_db()
    # Ensure default users exist (first-run convenience)
    _ensure_default_users()
    docs = db.collection('USER').where('USERNAME', '==', username).where('PASSWORD', '==', password).limit(1).get()
    return docs[0].to_dict() if docs else None

# ==================================================
# DETERGENT TABLE
# - add_detergent(): create detergent item
# - update_detergent(): edit detergent
# - delete_detergent(): remove detergent
# - get_all_detergents(): list items
# - get_detergent_by_id(): fetch single item
# - search_detergents(): simple name/ID search
# - get_detergent_total_value(): compute total value
# ==================================================
def add_detergent(name: str, price: float, qty: int, image_filename: str = None) -> bool:
    """Add a detergent to inventory with auto-increment DETERGENT_ID."""
    _require_db()
    transaction = db.transaction()
    det_id = _get_next_id(transaction, 'DETERGENT_ID')
    now = _now()
    db.collection('DETERGENT').add({
        'DETERGENT_ID': det_id,
        'DETERGENT_NAME': name,
        'DETERGENT_PRICE': float(price),
        'QTY': int(qty),
        'DATE_CREATED': now,
        'DATE_UPDATED': now,
        'IMAGE_FILENAME': image_filename,
    })
    return True

def update_detergent(detergent_id: int, name: str, price: float, qty: int, image_filename: str = None) -> bool:
    """Update a detergent by DETERGENT_ID."""
    _require_db()
    docs = db.collection('DETERGENT').where('DETERGENT_ID', '==', detergent_id).limit(1).get()
    if not docs:
        return False
    db.collection('DETERGENT').document(docs[0].id).update({
        'DETERGENT_NAME': name,
        'DETERGENT_PRICE': float(price),
        'QTY': int(qty),
        'DATE_UPDATED': _now(),
        'IMAGE_FILENAME': image_filename,
    })
    return True

def delete_detergent(detergent_id: int) -> bool:
    """Delete a detergent by DETERGENT_ID."""
    _require_db()
    docs = db.collection('DETERGENT').where('DETERGENT_ID', '==', detergent_id).limit(1).get()
    if not docs:
        return False
    db.collection('DETERGENT').document(docs[0].id).delete()
    return True

def get_all_detergents() -> list:
    """Return all detergents ordered by name."""
    _require_db()
    docs = db.collection('DETERGENT').order_by('DETERGENT_NAME').get()
    return [doc.to_dict() for doc in docs]

def get_detergent_by_id(detergent_id: int) -> dict:
    """Fetch a detergent by DETERGENT_ID."""
    _require_db()
    docs = db.collection('DETERGENT').where('DETERGENT_ID', '==', detergent_id).limit(1).get()
    return docs[0].to_dict() if docs else None

def search_detergents(query: str) -> list:
    """Search detergents by partial name or ID (simple client-side filter)."""
    _require_db()
    q = query.lower()
    docs = db.collection('DETERGENT').get()
    results = []
    for doc in docs:
        d = doc.to_dict()
        if q in d.get('DETERGENT_NAME', '').lower() or q in str(d.get('DETERGENT_ID', '')):
            results.append(d)
    results.sort(key=lambda x: x.get('DETERGENT_NAME', ''))
    return results

def get_detergent_total_value() -> dict:
    """Compute total inventory value for detergents (price * qty)."""
    _require_db()
    docs = db.collection('DETERGENT').get()
    total = 0.0
    for doc in docs:
        d = doc.to_dict()
        total += float(d.get('DETERGENT_PRICE', 0)) * int(d.get('QTY', 0))
    return {'ItemType': 'Detergent', 'TotalValue': total}

# ==================================================
# FABCON TABLE (Fabric Conditioner)
# - add_fabric_conditioner(): create fabcon item
# - update_fabric_conditioner(): edit fabcon
# - delete_fabric_conditioner(): remove fabcon
# - get_all_fabric_conditioners(): list items
# - get_fabric_conditioner_by_id(): fetch single item
# - search_fabric_conditioners(): simple name/ID search
# - get_fabcon_total_value(): compute total value
# ==================================================
def add_fabric_conditioner(name: str, price: float, qty: int, image_filename: str = None) -> bool:
    """Add a fabric conditioner to inventory with auto-increment FABCON_ID."""
    _require_db()
    transaction = db.transaction()
    fab_id = _get_next_id(transaction, 'FABCON_ID')
    now = _now()
    db.collection('FABCON').add({
        'FABCON_ID': fab_id,
        'FABCON_NAME': name,
        'FABCON_PRICE': float(price),
        'QTY': int(qty),
        'DATE_CREATED': now,
        'DATE_UPDATED': now,
        'IMAGE_FILENAME': image_filename,
    })
    return True

def update_fabric_conditioner(fabric_conditioner_id: int, name: str, price: float, qty: int, image_filename: str = None) -> bool:
    """Update a fabric conditioner by FABCON_ID."""
    _require_db()
    docs = db.collection('FABCON').where('FABCON_ID', '==', fabric_conditioner_id).limit(1).get()
    if not docs:
        return False
    db.collection('FABCON').document(docs[0].id).update({
        'FABCON_NAME': name,
        'FABCON_PRICE': float(price),
        'QTY': int(qty),
        'DATE_UPDATED': _now(),
        'IMAGE_FILENAME': image_filename,
    })
    return True

def delete_fabric_conditioner(fabric_conditioner_id: int) -> bool:
    """Delete a fabric conditioner by FABCON_ID."""
    _require_db()
    docs = db.collection('FABCON').where('FABCON_ID', '==', fabric_conditioner_id).limit(1).get()
    if not docs:
        return False
    db.collection('FABCON').document(docs[0].id).delete()
    return True

def get_all_fabric_conditioners() -> list:
    """Return all fabric conditioners ordered by name."""
    _require_db()
    docs = db.collection('FABCON').order_by('FABCON_NAME').get()
    return [doc.to_dict() for doc in docs]

def get_fabric_conditioner_by_id(fabric_conditioner_id: int) -> dict:
    """Fetch a fabric conditioner by FABCON_ID."""
    _require_db()
    docs = db.collection('FABCON').where('FABCON_ID', '==', fabric_conditioner_id).limit(1).get()
    return docs[0].to_dict() if docs else None

def search_fabric_conditioners(query: str) -> list:
    """Search fabric conditioners by partial name or ID (client-side filter)."""
    _require_db()
    q = query.lower()
    docs = db.collection('FABCON').get()
    results = []
    for doc in docs:
        d = doc.to_dict()
        if q in d.get('FABCON_NAME', '').lower() or q in str(d.get('FABCON_ID', '')):
            results.append(d)
    results.sort(key=lambda x: x.get('FABCON_NAME', ''))
    return results

def get_fabcon_total_value() -> dict:
    """Compute total inventory value for fabric conditioners (price * qty)."""
    _require_db()
    docs = db.collection('FABCON').get()
    total = 0.0
    for doc in docs:
        d = doc.to_dict()
        total += float(d.get('FABCON_PRICE', 0)) * int(d.get('QTY', 0))
    return {'ItemType': 'Fabric Conditioner', 'TotalValue': total}

##################################################
# ORDER_ITEM TABLE
# - add_order_item(): create order item flags/options
##################################################
def add_order_item(customer_own_detergent: bool, customer_own_fabcon: bool, iron: bool, fold_clothes: bool, prioritize_order: bool) -> int:
    """Create an ORDER_ITEM record and return its ORDERITEM_ID."""
    _require_db()
    transaction = db.transaction()
    orderitem_id = _get_next_id(transaction, 'ORDERITEM_ID')
    db.collection('ORDER_ITEM').add({
        'ORDERITEM_ID': orderitem_id,
        'CUSTOMER_OWN_DETERGENT': bool(customer_own_detergent),
        'CUSTOMER_OWN_FABCON': bool(customer_own_fabcon),
        'IRON': bool(iron),
        'FOLD_CLOTHES': bool(fold_clothes),
        'PRIORITIZE_ORDER': bool(prioritize_order),
        'DATE_CREATED': _now(),
    })
    return orderitem_id

##################################################
# ORDERITEM_DETERGENT (JUNCTION TABLE)
# - add_orderitem_detergent(): link ORDER_ITEM to DETERGENT
##################################################
def add_orderitem_detergent(orderitem_id: int, detergent_id: int, quantity: int, unit_price: float) -> bool:
    """Link an ORDER_ITEM to a DETERGENT with quantity and unit price.
    Prevent duplicate (ORDERITEM_ID, DETERGENT_ID) pairs (mimics SQL PK).
    """
    _require_db()
    docs = db.collection('ORDERITEM_DETERGENT') \
        .where(field_path='ORDERITEM_ID', op_string='==', value=orderitem_id) \
        .where(field_path='DETERGENT_ID', op_string='==', value=detergent_id).limit(1).get()
    if docs:
        return False
    db.collection('ORDERITEM_DETERGENT').add({
        'ORDERITEM_ID': orderitem_id,
        'DETERGENT_ID': detergent_id,
        'QUANTITY': int(quantity),
        'UNIT_PRICE': float(unit_price),
    })
    return True

##################################################
# ORDERITEM_FABCON (JUNCTION TABLE)
# - add_orderitem_fabcon(): link ORDER_ITEM to FABCON
##################################################
def add_orderitem_fabcon(orderitem_id: int, fabcon_id: int, quantity: int, unit_price: float) -> bool:
    """Link an ORDER_ITEM to a FABCON with quantity and unit price.
    Prevent duplicate (ORDERITEM_ID, FABCON_ID) pairs (mimics SQL PK).
    """
    _require_db()
    docs = db.collection('ORDERITEM_FABCON') \
        .where(field_path='ORDERITEM_ID', op_string='==', value=orderitem_id) \
        .where(field_path='FABCON_ID', op_string='==', value=fabcon_id).limit(1).get()
    if docs:
        return False
    db.collection('ORDERITEM_FABCON').add({
        'ORDERITEM_ID': orderitem_id,
        'FABCON_ID': fabcon_id,
        'QUANTITY': int(quantity),
        'UNIT_PRICE': float(unit_price),
    })
    return True

##################################################
# ORDER TABLE
# - add_order(): create order
# - get_order_by_id(): fetch order
# - update_order_payment(): set payment method/status
##################################################
def add_order(customer_id: int, orderitem_id: int, user_id: int, order_type: str, 
              total_weight: float, total_load: int, total_price: float, 
              order_note: str = None, pickup_schedule: str = None,
              order_status: str = 'Pending', payment_method: str = None, 
              payment_status: str = 'Unpaid') -> int:
    """Create a new ORDER row and return its ORDER_ID."""
    _require_db()
    transaction = db.transaction()
    order_id = _get_next_id(transaction, 'ORDER_ID')
    db.collection('ORDER').add({
        'ORDER_ID': order_id,
        'CUSTOMER_ID': customer_id,
        'ORDERITEM_ID': orderitem_id,
        'USER_ID': user_id,
        'ORDER_TYPE': order_type,
        'TOTAL_WEIGHT': float(total_weight),
        'TOTAL_LOAD': int(total_load),
        'TOTAL_PRICE': float(total_price),
        'QR_CODE': None,
        'RECEIPT_PATH': None,
        'ORDER_NOTE': order_note,
        'ORDER_STATUS': order_status,
        'PAYMENT_METHOD': payment_method,
        'PAYMENT_STATUS': payment_status,
        'PICKUP_SCHEDULE': pickup_schedule,
        'DATE_CREATED': _now(),
        'DATE_UPDATED': _now(),
    })
    return order_id

def get_order_by_id(order_id):
    """Fetch an ORDER by ORDER_ID."""
    _require_db()
    docs = db.collection('ORDER').where('ORDER_ID', '==', order_id).limit(1).get()
    return docs[0].to_dict() if docs else None

def get_orderitem_by_id(orderitem_id):
    """Fetch an ORDER_ITEM by ORDERITEM_ID."""
    _require_db()
    docs = db.collection('ORDER_ITEM').where('ORDERITEM_ID', '==', orderitem_id).limit(1).get()
    return docs[0].to_dict() if docs else None

def get_latest_customer():
    """Get the most recently added customer by DATE_CREATED descending."""
    _require_db()
    docs = db.collection('CUSTOMER').order_by('DATE_CREATED', direction=firestore.Query.DESCENDING).limit(1).get()
    return docs[0].to_dict() if docs else None

##################################################
# REPORT/RETRIEVAL HELPERS (ORDER ITEMS DETAIL)
# - get_orderitem_detergents(): list detergents in an order item
##################################################
def get_orderitem_detergents(orderitem_id):
    """Return detergents linked to an ORDER_ITEM with computed line totals."""
    _require_db()
    # Fetch junction entries then enrich names
    jdocs = db.collection('ORDERITEM_DETERGENT').where('ORDERITEM_ID', '==', orderitem_id).get()
    out = []
    for j in jdocs:
        jd = j.to_dict()
        ddocs = db.collection('DETERGENT').where('DETERGENT_ID', '==', jd['DETERGENT_ID']).limit(1).get()
        name = ddocs[0].to_dict().get('DETERGENT_NAME') if ddocs else 'Unknown'
        total_price = float(jd.get('UNIT_PRICE', 0)) * int(jd.get('QUANTITY', 0))
        out.append({'DETERGENT_NAME': name, 'QUANTITY': jd.get('QUANTITY', 0), 'UNIT_PRICE': jd.get('UNIT_PRICE', 0), 'total_price': total_price})
    return out

##################################################
# REPORT/RETRIEVAL HELPERS (ORDER ITEMS DETAIL)
# - get_orderitem_fabcons(): list fabcons in an order item
##################################################
def get_orderitem_fabcons(orderitem_id):
    """Return fabric conditioners linked to an ORDER_ITEM with line totals."""
    _require_db()
    jdocs = db.collection('ORDERITEM_FABCON').where('ORDERITEM_ID', '==', orderitem_id).get()
    out = []
    for j in jdocs:
        jd = j.to_dict()
        fdocs = db.collection('FABCON').where('FABCON_ID', '==', jd['FABCON_ID']).limit(1).get()
        name = fdocs[0].to_dict().get('FABCON_NAME') if fdocs else 'Unknown'
        total_price = float(jd.get('UNIT_PRICE', 0)) * int(jd.get('QUANTITY', 0))
        out.append({'FABCON_NAME': name, 'QUANTITY': jd.get('QUANTITY', 0), 'UNIT_PRICE': jd.get('UNIT_PRICE', 0), 'total_price': total_price})
    return out

def update_order_payment(order_id, payment_method, payment_status):
    """Update payment method/status for an order and bump DATE_UPDATED."""
    _require_db()
    docs = db.collection('ORDER').where('ORDER_ID', '==', order_id).limit(1).get()
    if not docs:
        return False
    db.collection('ORDER').document(docs[0].id).update({
        'PAYMENT_METHOD': payment_method,
        'PAYMENT_STATUS': payment_status,
        'DATE_UPDATED': _now(),
    })
    return True

def update_order_qr_code(order_id, qr_code_path):
    """Update QR_CODE field for an order."""
    _require_db()
    docs = db.collection('ORDER').where('ORDER_ID', '==', order_id).limit(1).get()
    if not docs:
        return False
    db.collection('ORDER').document(docs[0].id).update({
        'QR_CODE': qr_code_path,
        'DATE_UPDATED': _now(),
    })
    return True

def get_customers_with_orders() -> list:
    """Get all customers with their latest order details."""
    _require_db()
    
    # Get all customers
    customers = []
    customer_docs = db.collection('CUSTOMER').order_by('CUSTOMER_ID').get()
    
    for customer_doc in customer_docs:
        customer = customer_doc.to_dict()
        
        try:
            # Get latest order for this customer
            order_docs = db.collection('ORDER') \
                .where('CUSTOMER_ID', '==', customer['CUSTOMER_ID']) \
                .order_by('DATE_CREATED', direction=firestore.Query.DESCENDING) \
                .limit(1) \
                .get()
                
            # Add order details to customer dict
            if len(order_docs) > 0:
                order = order_docs[0].to_dict()
                customer['ORDER_ID'] = order.get('ORDER_ID', 'N/A')
                customer['ORDER_STATUS'] = order.get('ORDER_STATUS', 'N/A')
                customer['PAYMENT_STATUS'] = order.get('PAYMENT_STATUS', 'N/A')
            else:
                customer['ORDER_ID'] = 'N/A'
                customer['ORDER_STATUS'] = 'N/A'
                customer['PAYMENT_STATUS'] = 'N/A'
                
        except Exception as e:
            # Fallback if index not ready: get all orders and sort in memory
            print(f"Warning: Falling back to client-side sorting: {str(e)}")
            all_customer_orders = db.collection('ORDER') \
                .where('CUSTOMER_ID', '==', customer['CUSTOMER_ID']) \
                .get()
                
            orders = [doc.to_dict() for doc in all_customer_orders]
            if orders:
                # Sort by date created
                latest_order = max(orders, key=lambda x: x.get('DATE_CREATED', datetime.min))
                customer['ORDER_ID'] = latest_order.get('ORDER_ID', 'N/A')
                customer['ORDER_STATUS'] = latest_order.get('ORDER_STATUS', 'N/A') 
                customer['PAYMENT_STATUS'] = latest_order.get('PAYMENT_STATUS', 'N/A')
            else:
                customer['ORDER_ID'] = 'N/A'
                customer['ORDER_STATUS'] = 'N/A'
                customer['PAYMENT_STATUS'] = 'N/A'
            
        customers.append(customer)
        
    return customers

def get_customer_statistics():
    """Get customer and order statistics."""
    _require_db()
    
    # Get all customers
    customer_docs = db.collection('CUSTOMER').get()
    total_customers = len(customer_docs)
    
    # Get last month's customer count for growth calculation
    last_month = datetime.now() - timedelta(days=30)
    last_month_customers = len(db.collection('CUSTOMER')
        .where('DATE_CREATED', '<', last_month).get())
    
    # Calculate monthly growth
    if last_month_customers > 0:
        monthly_growth = ((total_customers - last_month_customers) / last_month_customers) * 100
    else:
        monthly_growth = 100 if total_customers > 0 else 0
        
    # Get order counts
    order_docs = db.collection('ORDER').get()
    orders = [doc.to_dict() for doc in order_docs]
    
    paid_orders = len([o for o in orders if o.get('PAYMENT_STATUS', '').upper() == 'PAID'])
    pending_orders = len([o for o in orders if o.get('ORDER_STATUS', '').upper() == 'PENDING'])
    total_orders = len(orders)

    # Calculate percentages
    paid_percentage = (paid_orders / total_orders * 100) if total_orders > 0 else 0
    pending_percentage = (pending_orders / total_orders * 100) if total_orders > 0 else 0
    
    return {
        'total_customers': total_customers,
        'paid_orders': paid_orders,
        'pending_orders': pending_orders,
        'monthly_growth': round(monthly_growth, 1),
        'paid_percentage': round(paid_percentage, 1),
        'pending_percentage': round(pending_percentage, 1),
        'unpaid_percentage': round(100 - paid_percentage, 1),
        'monthly_data': get_monthly_customer_data()
    }

def get_monthly_customer_data():
    """Get customer counts for the last 6 months."""
    _require_db()
    
    months = []
    counts = []
    
    # Get last 6 months
    for i in range(5, -1, -1):
        start_date = datetime.now() - timedelta(days=30 * (i + 1))
        end_date = datetime.now() - timedelta(days=30 * i)
        
        # Count customers created in this month
        customer_count = len(db.collection('CUSTOMER')
            .where('DATE_CREATED', '>=', start_date)
            .where('DATE_CREATED', '<', end_date)
            .get())
            
        months.append(start_date.strftime('%b'))
        counts.append(customer_count)
    
    return {
        'months': months,
        'counts': counts
    }

def get_all_orders_with_priority():
    """Return all orders with priority info and customer name."""
    _require_db()
    orders = db.collection('ORDER').order_by('DATE_CREATED', direction=firestore.Query.DESCENDING).get()
    
    # COLLECT ALL UNIQUE ID FOR BATCHING
    orderitem_ids = set()
    customer_ids = set()
    orders_list = []
    
    for doc in orders:
        order = doc.to_dict()
        orders_list.append(order)
        if order.get('ORDERITEM_ID') is not None:
            orderitem_ids.add(order['ORDERITEM_ID'])
        if order.get('CUSTOMER_ID') is not None:
            customer_ids.add(order['CUSTOMER_ID'])
    
    # PER BATCH INSTEAD OF SINGLE QUERY 
    orderitem_map = {}
    if orderitem_ids:
        orderitem_ids_list = list(orderitem_ids)
        for i in range(0, len(orderitem_ids_list), 10):
            batch_ids = orderitem_ids_list[i:i+10]
            orderitem_docs = db.collection('ORDER_ITEM').where('ORDERITEM_ID', 'in', batch_ids).get()
            for doc in orderitem_docs:
                orderitem = doc.to_dict()
                orderitem_map[orderitem.get('ORDERITEM_ID')] = orderitem
    
    # PER BATCH INSTEAD OF SINGLE QUERY 
    customer_map = {}
    if customer_ids:
        customer_ids_list = list(customer_ids)
        for i in range(0, len(customer_ids_list), 10):
            batch_ids = customer_ids_list[i:i+10]
            customer_docs = db.collection('CUSTOMER').where('CUSTOMER_ID', 'in', batch_ids).get()
            for doc in customer_docs:
                customer = doc.to_dict()
                customer_map[customer.get('CUSTOMER_ID')] = customer
    
    out = []
    for order in orders_list:
        orderitem = orderitem_map.get(order.get('ORDERITEM_ID'))
        customer = customer_map.get(order.get('CUSTOMER_ID'))
        out.append({
            'ORDER_ID': order.get('ORDER_ID'),
            'CUSTOMER_ID': order.get('CUSTOMER_ID'),
            'CUSTOMER_NAME': customer.get('FULLNAME') if customer else '',
            'ORDER_TYPE': order.get('ORDER_TYPE'),
            'PRIORITY': 'Priority' if orderitem and orderitem.get('PRIORITIZE_ORDER') else 'Normal',
            'PAYMENT_STATUS': order.get('PAYMENT_STATUS'),
            'ORDER_STATUS': order.get('ORDER_STATUS'),
            'DATE_CREATED': order.get('DATE_CREATED'),
            'TOTAL_LOAD': order.get('TOTAL_LOAD'),
            'TOTAL_PRICE': order.get('TOTAL_PRICE'),
            'TOTAL_WEIGHT': order.get('TOTAL_WEIGHT'),
            'PICKUP_SCHEDULE': order.get('PICKUP_SCHEDULE'),
        })

    out.sort(key=lambda x: (x['PRIORITY'] != 'Priority', x['DATE_CREATED'] if x['DATE_CREATED'] else 0), reverse=False)
    return out

    
if __name__ == "__main__":
    initialize_database()
    print("Connected to Firebase Firestore successfully.")
