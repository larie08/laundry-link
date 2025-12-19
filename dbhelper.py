# BISAYA, TAGALOG UG ENGLISH NANING COMMENT PARA MAS MAKASABOT SI OKS OR KITANG TANAN HAHAHHAHAHAHHA 
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# FIRBASE SDK CODE - DAPAT ADMIN ARI
import firebase_admin
from firebase_admin import credentials, firestore

# PLACEHOLDER PALANG NIS FIRESTORE CLIENT (LAZY INITIALIZATION)
db = None

# TAX RATE FOR PHILIPPINES (12% VAT)
TAX_RATE = 0.12

# ARI NA JUD MAGSUGOD A TUNG HELPERS HAHHAHAH
# GLOBAL FIRESTORE CLIENT s
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
        try:
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
        except ValueError as e:
            # If already initialized elsewhere, just reuse existing app
            if 'already exists' not in str(e).lower():
                raise
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

    # SUPER ADMIN ACCOUNT
    super_admin_q = users_ref.where('USERNAME', '==', 'super_admin').limit(1).get()
    if not super_admin_q:
        transaction = db.transaction()
        super_admin_id = _get_next_id(transaction, 'USER_ID')
        users_ref.add({
            'USER_ID': super_admin_id,
            'USERNAME': 'superadmin',
            'PASSWORD': 'superadmin123',
            'ROLE': 'super_admin',
            'FULLNAME': 'Super Admin',
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
            # Update status to "Pick-up" if currently "Pending"
            if d.get('ORDER_STATUS', '').lower() == 'pending':
                db.collection('ORDER').document(doc.id).update({'ORDER_STATUS': 'Pick-up'})
                d['ORDER_STATUS'] = 'Pick-up'
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
def add_customer(fullname: str, phone_number: str, user_id: int = None) -> bool:
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
    # Log the action
    if user_id is not None:
        add_customer_log(user_id, 'Add', customer_id, fullname, phone_number)
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

def update_customer(customer_id: int, fullname: str, phone_number: str, user_id: int = None) -> bool:
    """Update FULLNAME and PHONE_NUMBER for a customer."""
    _require_db()
    docs = db.collection('CUSTOMER').where('CUSTOMER_ID', '==', customer_id).limit(1).get()
    if not docs:
        return False
    db.collection('CUSTOMER').document(docs[0].id).update({
        'FULLNAME': fullname,
        'PHONE_NUMBER': phone_number,
    })
    # Log the action
    if user_id is not None:
        add_customer_log(user_id, 'Update', customer_id, fullname, phone_number)
    return True

def delete_customer(customer_id: int, user_id: int = None) -> bool:
    """Delete a customer document by CUSTOMER_ID."""
    _require_db()
    docs = db.collection('CUSTOMER').where('CUSTOMER_ID', '==', customer_id).limit(1).get()
    if not docs:
        return False
    customer = docs[0].to_dict()
    db.collection('CUSTOMER').document(docs[0].id).delete()
    # Log the action
    if user_id is not None:
        add_customer_log(user_id, 'Delete', customer_id, customer.get('FULLNAME', ''), customer.get('PHONE_NUMBER', ''))
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

def delete_user(user_id: int) -> bool:
    """Delete a user by USER_ID."""
    _require_db()
    docs = db.collection('USER').where('USER_ID', '==', user_id).limit(1).get()
    if not docs:
        return False
    db.collection('USER').document(docs[0].id).delete()
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
def add_detergent(name: str, price: float, qty: int, image_filename: str = None, user_id: int = None) -> bool:
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
    # Log the action
    if user_id is not None:
        add_inventory_log(user_id, 'Add', 'Detergent', det_id, name, qty, price)
    return True

def update_detergent(detergent_id: int, name: str, price: float, qty: int, image_filename: str = None, user_id: int = None) -> bool:
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
    # Log the action
    if user_id is not None:
        add_inventory_log(user_id, 'Update', 'Detergent', detergent_id, name, qty, price)
    return True

def delete_detergent(detergent_id: int, user_id: int = None) -> bool:
    """Delete a detergent by DETERGENT_ID."""
    _require_db()
    docs = db.collection('DETERGENT').where('DETERGENT_ID', '==', detergent_id).limit(1).get()
    if not docs:
        return False
    det = docs[0].to_dict()
    db.collection('DETERGENT').document(docs[0].id).delete()
    # Log the action
    if user_id is not None:
        add_inventory_log(user_id, 'Delete', 'Detergent', detergent_id, det.get('DETERGENT_NAME', ''), det.get('QTY', 0), det.get('DETERGENT_PRICE', 0.0))
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
def add_fabric_conditioner(name: str, price: float, qty: int, image_filename: str = None, user_id: int = None) -> bool:
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
    # Log the action
    if user_id is not None:
        add_inventory_log(user_id, 'Add', 'Fabric Conditioner', fab_id, name, qty, price)
    return True

def update_fabric_conditioner(fabric_conditioner_id: int, name: str, price: float, qty: int, image_filename: str = None, user_id: int = None) -> bool:
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
    # Log the action
    if user_id is not None:
        add_inventory_log(user_id, 'Update', 'Fabric Conditioner', fabric_conditioner_id, name, qty, price)
    return True

def delete_fabric_conditioner(fabric_conditioner_id: int, user_id: int = None) -> bool:
    """Delete a fabric conditioner by FABCON_ID."""
    _require_db()
    docs = db.collection('FABCON').where('FABCON_ID', '==', fabric_conditioner_id).limit(1).get()
    if not docs:
        return False
    fab = docs[0].to_dict()
    db.collection('FABCON').document(docs[0].id).delete()
    # Log the action
    if user_id is not None:
        add_inventory_log(user_id, 'Delete', 'Fabric Conditioner', fabric_conditioner_id, fab.get('FABCON_NAME', ''), fab.get('QTY', 0), fab.get('FABCON_PRICE', 0.0))
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
        .where('ORDERITEM_ID', '==', orderitem_id) \
        .where('DETERGENT_ID', '==', detergent_id).limit(1).get()
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
        .where('ORDERITEM_ID', '==', orderitem_id) \
        .where('FABCON_ID', '==', fabcon_id).limit(1).get()
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
              payment_status: str = 'Unpaid', tax: float = 0.0) -> int:
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
        'TAX': float(tax),
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

def update_order_payment(order_id, payment_method, payment_status, user_id: int = None):
    """Update payment method/status for an order and bump DATE_UPDATED."""
    _require_db()
    docs = db.collection('ORDER').where('ORDER_ID', '==', order_id).limit(1).get()
    if not docs:
        return False
    
    # Get old payment status for logging
    old_data = docs[0].to_dict()
    old_payment_status = old_data.get('PAYMENT_STATUS', 'Unknown')
    
    db.collection('ORDER').document(docs[0].id).update({
        'PAYMENT_METHOD': payment_method,
        'PAYMENT_STATUS': payment_status,
        'DATE_UPDATED': _now(),
    })
    
    # Log the payment status change
    detail = f"{old_payment_status} -> {payment_status}"
    add_order_log(order_id, 'Payment Update', detail, user_id)
    
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

def update_order_note(order_id, order_note):
    """Update ORDER_NOTE field for an order."""
    _require_db()
    docs = db.collection('ORDER').where('ORDER_ID', '==', order_id).limit(1).get()
    if not docs:
        return False
    # If order_note is empty, set to None
    note_value = order_note.strip() if order_note and order_note.strip() else None
    db.collection('ORDER').document(docs[0].id).update({
        'ORDER_NOTE': note_value,
        'DATE_UPDATED': _now(),
    })
    return True

def update_order_status(order_id, status, user_id: int = None):
    """Update ORDER_STATUS field for an order."""
    _require_db()
    docs = db.collection('ORDER').where('ORDER_ID', '==', order_id).limit(1).get()
    if not docs:
        return False
    
    # Get old status for logging
    old_data = docs[0].to_dict()
    old_status = old_data.get('ORDER_STATUS', 'Unknown')
    
    db.collection('ORDER').document(docs[0].id).update({
        'ORDER_STATUS': status,
        'DATE_UPDATED': _now(),
    })
    
    # Log the status change
    detail = f"{old_status} -> {status}"
    add_order_log(order_id, 'Status Update', detail, user_id)
    
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

def get_all_customers_with_order_stats():
    """Return all customers with their latest order and order count (batch, fast)."""
    _require_db()
    customers = []
    customer_docs = db.collection('CUSTOMER').order_by('CUSTOMER_ID').get()
    orders = db.collection('ORDER').get()
    orders_by_customer = {}
    for doc in orders:
        order = doc.to_dict()
        cid = order.get('CUSTOMER_ID')
        if cid not in orders_by_customer:
            orders_by_customer[cid] = []
        orders_by_customer[cid].append(order)
    for customer_doc in customer_docs:
        customer = customer_doc.to_dict()
        cid = customer['CUSTOMER_ID']
        cust_orders = orders_by_customer.get(cid, [])
        customer['total_orders'] = len(cust_orders)
        # Add CUSTOMER_NAME for template compatibility
        customer['CUSTOMER_NAME'] = customer.get('FULLNAME', '')
        if cust_orders:
            latest_order = max(cust_orders, key=lambda x: x.get('DATE_CREATED', datetime.min))
            customer['ORDER_ID'] = latest_order.get('ORDER_ID', 'N/A')
            customer['ORDER_STATUS'] = latest_order.get('ORDER_STATUS', 'N/A')
            customer['PAYMENT_STATUS'] = latest_order.get('PAYMENT_STATUS', 'N/A')
            # Add ORDER_TYPE and TOTAL_PRICE for template compatibility
            customer['ORDER_TYPE'] = latest_order.get('ORDER_TYPE', '')
            customer['TOTAL_PRICE'] = latest_order.get('TOTAL_PRICE', '')
        else:
            customer['ORDER_ID'] = 'N/A'
            customer['ORDER_STATUS'] = 'N/A'
            customer['PAYMENT_STATUS'] = 'N/A'
            customer['ORDER_TYPE'] = ''
            customer['TOTAL_PRICE'] = ''
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

def get_daily_customer_counts():
    """Get customer counts by day for the last 30 days."""
    _require_db()
    
    daily_counts = {}
    
    # Get all customers
    customers = db.collection('CUSTOMER').get()
    
    # Count customers added each day
    for doc in customers:
        customer = doc.to_dict()
        if customer.get('DATE_CREATED'):
            date_created = customer['DATE_CREATED']
            # Convert to date only (remove time)
            if hasattr(date_created, 'date'):
                date_key = date_created.date()
            else:
                date_key = date_created
            
            if date_key not in daily_counts:
                daily_counts[date_key] = 0
            daily_counts[date_key] += 1
    
    return daily_counts

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
            'ORDERITEM_ID': order.get('ORDERITEM_ID'),
            'CUSTOMER_ID': order.get('CUSTOMER_ID'),
            'CUSTOMER_NAME': customer.get('FULLNAME') if customer else '',
            'PHONE_NUMBER': customer.get('PHONE_NUMBER') if customer else '',
            'ORDER_TYPE': order.get('ORDER_TYPE'),
            'PRIORITY': 'Priority' if orderitem and orderitem.get('PRIORITIZE_ORDER') else 'Normal',
            'PAYMENT_STATUS': order.get('PAYMENT_STATUS'),
            'ORDER_STATUS': order.get('ORDER_STATUS'),
            'DATE_UPDATED': order.get('DATE_UPDATED'),
            'DATE_CREATED': order.get('DATE_CREATED'),
            'TOTAL_LOAD': order.get('TOTAL_LOAD'),
            'TOTAL_PRICE': order.get('TOTAL_PRICE'),
            'TOTAL_WEIGHT': order.get('TOTAL_WEIGHT'),
            'PICKUP_SCHEDULE': order.get('PICKUP_SCHEDULE'),
        })

    out.sort(key=lambda x: (x['PRIORITY'] != 'Priority', x['DATE_CREATED'] if x['DATE_CREATED'] else 0), reverse=False)
    return out

def add_order_log(order_id: int, action: str, detail: str, user_id: int = None):
    """Log order updates (status/payment changes)."""
    _require_db()
    db.collection('ORDER_LOG').add({
        'ORDER_ID': order_id,
        'ACTION': action,  # 'Status Update', 'Payment Update'
        'DETAIL': detail,  # e.g., 'Pending -> Pick-up' or 'Unpaid -> PAID'
        'USER_ID': user_id,
        'DATE': _now(),
    })

def add_inventory_log(user_id: int, action: str, item_type: str, item_id: int, name: str, qty: int, price: float):
    """Add an inventory log entry for detergent/fabcon actions."""
    _require_db()
    db.collection('INVENTORY_LOG').add({
        'USER_ID': user_id,
        'ACTION': action,  # 'Add', 'Update', 'Delete'
        'ITEM_TYPE': item_type,  # 'Detergent' or 'Fabric Conditioner'
        'ITEM_ID': item_id,
        'NAME': name,
        'QTY': qty,
        'PRICE': price,
        'DATE': _now(),
    })

def add_customer_log(user_id: int, action: str, customer_id: int, fullname: str, phone_number: str):
    """Log customer actions (add, update, delete)."""
    _require_db()
    db.collection('CUSTOMER_LOG').add({
        'USER_ID': user_id,
        'ACTION': action,  # 'Add', 'Update', 'Delete'
        'CUSTOMER_ID': customer_id,
        'FULLNAME': fullname,
        'PHONE_NUMBER': phone_number,
        'DATE': _now(),
    })

##################################################
# CONSUMED INVENTORY REPORT FUNCTIONS
# - get_consumed_detergents_report(): get consumed detergents with total value
# - get_consumed_fabcons_report(): get consumed fabric conditioners with total value
##################################################
def get_consumed_detergents_report() -> list:
    """
    Get all consumed detergents from ORDERITEM_DETERGENT junction table.
    Joins with ORDER_ITEM, ORDER, DETERGENT to get full details.
    Returns: List of dicts with detergent consumption data and total cost.
    """
    _require_db()
    
    # Get all ORDERITEM_DETERGENT records
    orderitem_det_docs = db.collection('ORDERITEM_DETERGENT').get()
    out = []
    
    for doc in orderitem_det_docs:
        oid_det = doc.to_dict()
        orderitem_id = oid_det.get('ORDERITEM_ID')
        detergent_id = oid_det.get('DETERGENT_ID')
        quantity = int(oid_det.get('QUANTITY', 0))
        unit_price = float(oid_det.get('UNIT_PRICE', 0))
        total_value = quantity * unit_price
        
        # Get ORDER_ITEM to link to ORDER
        orderitem_docs = db.collection('ORDER_ITEM').where('ORDERITEM_ID', '==', orderitem_id).limit(1).get()
        if not orderitem_docs:
            continue
        
        # Get ORDER to get date and order details
        order_docs = db.collection('ORDER').where('ORDERITEM_ID', '==', orderitem_id).limit(1).get()
        if not order_docs:
            continue
        
        order = order_docs[0].to_dict()
        date_created = order.get('DATE_CREATED')
        
        # Get DETERGENT to get name
        detergent_docs = db.collection('DETERGENT').where('DETERGENT_ID', '==', detergent_id).limit(1).get()
        detergent_name = 'Unknown'
        if detergent_docs:
            detergent_name = detergent_docs[0].to_dict().get('DETERGENT_NAME', 'Unknown')
        
        out.append({
            'DETERGENT_ID': detergent_id,
            'DETERGENT_NAME': detergent_name,
            'QUANTITY': quantity,
            'UNIT_PRICE': unit_price,
            'TOTAL_VALUE': total_value,
            'DATE_CREATED': date_created,
            'ORDER_ID': order.get('ORDER_ID'),
            # Include status so callers can filter (e.g., completed-only views)
            'ORDER_STATUS': order.get('ORDER_STATUS')
        })
    
    return out

def get_consumed_fabcons_report() -> list:
    """
    Get all consumed fabric conditioners from ORDERITEM_FABCON junction table.
    Joins with ORDER_ITEM, ORDER, FABCON to get full details.
    Returns: List of dicts with fabric conditioner consumption data and total cost.
    """
    _require_db()
    
    # Get all ORDERITEM_FABCON records
    orderitem_fab_docs = db.collection('ORDERITEM_FABCON').get()
    out = []
    
    for doc in orderitem_fab_docs:
        oid_fab = doc.to_dict()
        orderitem_id = oid_fab.get('ORDERITEM_ID')
        fabcon_id = oid_fab.get('FABCON_ID')
        quantity = int(oid_fab.get('QUANTITY', 0))
        unit_price = float(oid_fab.get('UNIT_PRICE', 0))
        total_value = quantity * unit_price
        
        # Get ORDER_ITEM to link to ORDER
        orderitem_docs = db.collection('ORDER_ITEM').where('ORDERITEM_ID', '==', orderitem_id).limit(1).get()
        if not orderitem_docs:
            continue
        
        # Get ORDER to get date and order details
        order_docs = db.collection('ORDER').where('ORDERITEM_ID', '==', orderitem_id).limit(1).get()
        if not order_docs:
            continue
        
        order = order_docs[0].to_dict()
        date_created = order.get('DATE_CREATED')
        
        # Get FABCON to get name
        fabcon_docs = db.collection('FABCON').where('FABCON_ID', '==', fabcon_id).limit(1).get()
        fabcon_name = 'Unknown'
        if fabcon_docs:
            fabcon_name = fabcon_docs[0].to_dict().get('FABCON_NAME', 'Unknown')
        
        out.append({
            'FABCON_ID': fabcon_id,
            'FABCON_NAME': fabcon_name,
            'QUANTITY': quantity,
            'UNIT_PRICE': unit_price,
            'TOTAL_VALUE': total_value,
            'DATE_CREATED': date_created,
            'ORDER_ID': order.get('ORDER_ID'),
            # Include status so callers can filter (e.g., completed-only views)
            'ORDER_STATUS': order.get('ORDER_STATUS')
        })
    
    return out

def compute_order_stats(orders: list, days: int = 7) -> dict:
    """Aggregate status/type counts and build a short-term trend series.

    Args:
        orders: List of order dictionaries (as returned by get_all_orders_with_priority()).
        days: Number of trailing days (including today) for the trend series.

    Returns:
        dict with keys:
            - status_counts: dict of Pending/Pick-up/Completed/Other
            - type_counts: dict of Self-service/Drop-off/Other
            - trend: {labels: [...], counts: [...]}
    """
    status_counts = {"Pending": 0, "Pick-up": 0, "Completed": 0, "Other": 0}
    type_counts = {"Self-service": 0, "Drop-off": 0, "Other": 0}

    # Normalize helpers
    def _norm_status(raw):
        if not raw:
            return "Other"
        s = str(raw).lower()
        if "pending" in s:
            return "Pending"
        if "pickup" in s or "pick-up" in s or "pick up" in s:
            return "Pick-up"
        if "completed" in s or "complete" in s or "done" in s:
            return "Completed"
        return "Other"

    def _norm_type(raw):
        if not raw:
            return "Other"
        t = str(raw).lower().replace("_", "").replace(" ", "")
        if "selfservice" in t or t == "self":
            return "Self-service"
        if "dropoff" in t or "drop" == t:
            return "Drop-off"
        return "Other"

    today = datetime.now().date()
    trend_labels = []
    trend_counts = []
    # Precompute dates for quick comparison
    bucket_dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]

    for order in orders:
        status = _norm_status(order.get("ORDER_STATUS"))
        otype = _norm_type(order.get("ORDER_TYPE"))
        status_counts[status] = status_counts.get(status, 0) + 1
        type_counts[otype] = type_counts.get(otype, 0) + 1

    # Trend: count orders per day for the chosen window
    for d in bucket_dates:
        trend_labels.append(d.strftime("%b %d"))
        count = 0
        for order in orders:
            date_created = order.get("DATE_CREATED")
            if not date_created:
                continue
            # Handle both Firestore timestamp-like and datetime objects
            if hasattr(date_created, "date"):
                order_date = date_created.date()
            elif isinstance(date_created, datetime):
                order_date = date_created.date()
            else:
                continue
            if order_date == d:
                count += 1
        trend_counts.append(count)

    return {
        "status_counts": status_counts,
        "type_counts": type_counts,
        "trend": {"labels": trend_labels, "counts": trend_counts},
    }


def deduct_detergent_quantity(detergent_id: int, quantity: int) -> bool:
    """Deduct quantity from detergent inventory when order is placed.
    
    Args:
        detergent_id: The DETERGENT_ID to deduct from
        quantity: The quantity to deduct
        
    Returns:
        True if deduction was successful, False otherwise
    """
    _require_db()
    docs = db.collection('DETERGENT').where('DETERGENT_ID', '==', detergent_id).limit(1).get()
    if not docs:
        return False
    
    detergent = docs[0].to_dict()
    current_qty = int(detergent.get('QTY', 0))
    new_qty = max(0, current_qty - quantity)  # Ensure qty doesn't go negative
    
    db.collection('DETERGENT').document(docs[0].id).update({
        'QTY': new_qty,
        'DATE_UPDATED': _now(),
    })
    return True

def deduct_fabcon_quantity(fabcon_id: int, quantity: int) -> bool:
    """Deduct quantity from fabric conditioner inventory when order is placed.
    
    Args:
        fabcon_id: The FABCON_ID to deduct from
        quantity: The quantity to deduct
        
    Returns:
        True if deduction was successful, False otherwise
    """
    _require_db()
    docs = db.collection('FABCON').where('FABCON_ID', '==', fabcon_id).limit(1).get()
    if not docs:
        return False
    
    fabcon = docs[0].to_dict()
    current_qty = int(fabcon.get('QTY', 0))
    new_qty = max(0, current_qty - quantity)  # Ensure qty doesn't go negative
    
    db.collection('FABCON').document(docs[0].id).update({
        'QTY': new_qty,
        'DATE_UPDATED': _now(),
    })
    return True



    
    initialize_database()
    print("Connected to Firebase Firestore successfully.")


# ==================================================
# SHOP / DEVICE MANAGEMENT
# ==================================================

def get_all_shops() -> list:
    """
    Fetch all 'shops' (users with role='admin').
    Returns a list of dicts with STATUS fields for display.
    """
    _require_db()
    
    # Get all users with role 'admin'
    docs = db.collection('USER').where('ROLE', '==', 'admin').get()
    shops = []
    
    for doc in docs:
        user = doc.to_dict()
        user_id = user.get('USER_ID')
        
        # In a real deployed scenario, this might check a heartbeat collection.
        # For now, we persist the "status" in the USER document itself (KIOSK_STATUS).
        # Detailed "last_seen" could be updated by an actual device heartbeat API.
        
        # Default to 'offline' if not set
        status = user.get('KIOSK_STATUS', 'offline')
        
        # Mocking last_seen based on status for realism if not present
        if status == 'online':
            last_seen = _now().strftime('%Y-%m-%d %H:%M')
        else:
             # Just a placeholder for offline devices
            last_seen = (datetime.now() - timedelta(hours=4)).strftime('%Y-%m-%d %H:%M')

        # If the DB has a real LAST_SEEN field, use it
        if user.get('LAST_SEEN'):
             # Handle if it is a firestore datetime
            ls = user.get('LAST_SEEN')
            if hasattr(ls, 'strftime'):
                last_seen = ls.strftime('%Y-%m-%d %H:%M')
            else:
                last_seen = str(ls)

        shops.append({
            'SHOP_ID': user_id,
            'SHOP_NAME': user.get('FULLNAME', 'Unknown Shop'),
            'kiosk': {'status': status, 'last_seen': last_seen},
        })
        
    return shops

def update_device_status(user_id: int, status: str) -> bool:
    """Update the KIOSK_STATUS for a shop (user_id)."""
    _require_db()
    
    docs = db.collection('USER').where('USER_ID', '==', user_id).limit(1).get()
    if not docs:
        return False
    
    update_data = {
        'KIOSK_STATUS': status,
        'DATE_UPDATED': _now()
    }
    
    # If setting to online, update LAST_SEEN too
    if status == 'online':
        update_data['LAST_SEEN'] = _now()
        
    db.collection('USER').document(docs[0].id).update(update_data)
    return True

def calculate_storage_fee(order_id: int) -> dict:
    """Calculate storage fee based on pickup schedule.
    
    Fee Structure:
    - 0-1 days overdue: 0
    - 2 days overdue: 20 pesos
    - Each additional day: +20 pesos
    """
    _require_db()
    
    # Get order
    docs = db.collection('ORDER').where('ORDER_ID', '==', order_id).limit(1).get()
    if not docs:
        return {'fee': 0.0, 'days_overdue': 0, 'schedule': None}
    
    order = docs[0].to_dict()
    schedule_str = order.get('PICKUP_SCHEDULE')
    
    if not schedule_str:
        return {'fee': 0.0, 'days_overdue': 0, 'schedule': None}
        
    try:
        # Format: "October 24, 2024, 02:00 PM"
        schedule_dt = datetime.strptime(schedule_str, '%B %d, %Y, %I:%M %p')
        now = _now()
        
        # Calculate full days overdue
        diff = now - schedule_dt
        days_overdue = diff.days
        
        fee = 0.0
        if days_overdue >= 2:
            # Base fee for 2nd day is 20
            # Additional days are 20 each
            # Formula: 20 + (days_overdue - 2) * 20
            fee = 20.0 + ((days_overdue - 2) * 20.0)
            
        return {
            'fee': fee, 
            'days_overdue': max(0, days_overdue),
            'schedule': schedule_str
        }
        
    except ValueError:
        # Handle parsing errors gracefully
        print(f"Error parsing date: {schedule_str}")
        return {'fee': 0.0, 'days_overdue': 0, 'schedule': schedule_str}