import pyodbc

# # SQL Server connection setup(I comment lang pls)-cedyy
# SERVER = 'LAPTOP-2E6VUSUM\\SQLEXPRESS' # Change this to your server name
# DATABASE = 'LAUNDRYLINK_DB'         # Change this to your database name

# DO NOT DELETE THIS PLEASE, JUST COMMENT IT OUT ~~ ALEXA
SERVER = 'DESKTOP-EPCAAU1\\SQLEXPRESS' 
DATABASE = 'LAUNDRYLINK'         

def get_connection():
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        f"Trusted_Connection=yes;"
    )
    return pyodbc.connect(conn_str)

def initialize_database():
    conn = get_connection()
    cursor = conn.cursor()

    # CUSTOMER table
    cursor.execute('''
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='CUSTOMER' AND xtype='U')
    CREATE TABLE CUSTOMER (
        CUSTOMER_ID INT PRIMARY KEY IDENTITY(1,1),
        FULLNAME VARCHAR(100),
        PHONE_NUMBER VARCHAR(20),
        DATE_CREATED DATETIME
    )
    ''')

    # USER table
    cursor.execute('''
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='USER' AND xtype='U')
    CREATE TABLE [USER] (
        USER_ID INT PRIMARY KEY IDENTITY(1,1),
        USERNAME VARCHAR(50),
        PASSWORD VARCHAR(255),
        ROLE VARCHAR(20),
        FULLNAME VARCHAR(100),
        DATE_CREATED DATETIME
    )
    ''')

    # ORDER_ITEM table
    cursor.execute('''
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ORDER_ITEM' AND xtype='U')
    CREATE TABLE ORDER_ITEM (
        ORDERITEM_ID INT PRIMARY KEY IDENTITY(1,1),
        CUSTOMER_OWN_DETERGENT BIT,
        CUSTOMER_OWN_FABCON BIT,
        IRON BIT,
        FOLD_CLOTHES BIT,
        PRIORITIZE_ORDER BIT,
        DATE_CREATED DATETIME
    )
    ''')

    # DETERGENT table
    cursor.execute('''
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='DETERGENT' AND xtype='U')
    CREATE TABLE DETERGENT (
        DETERGENT_ID INT PRIMARY KEY IDENTITY(1,1),
        DETERGENT_NAME VARCHAR(100),
        DETERGENT_PRICE DECIMAL(10,2),
        QTY SMALLINT,
        DATE_CREATED DATETIME,
        DATE_UPDATED DATETIME,
        IMAGE_FILENAME VARCHAR(255) NULL
    )
    ''')

    # FABCON table
    cursor.execute('''
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='FABCON' AND xtype='U')
    CREATE TABLE FABCON (
        FABCON_ID INT PRIMARY KEY IDENTITY(1,1),
        FABCON_NAME VARCHAR(100),
        FABCON_PRICE DECIMAL(10,2),
        QTY SMALLINT,
        DATE_CREATED DATETIME,
        DATE_UPDATED DATETIME,
        IMAGE_FILENAME VARCHAR(255) NULL
    )
    ''')

    # ORDER table
    cursor.execute('''
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ORDER' AND xtype='U')
    CREATE TABLE [ORDER] (
        ORDER_ID INT PRIMARY KEY IDENTITY(1,1),
        CUSTOMER_ID INT FOREIGN KEY REFERENCES CUSTOMER(CUSTOMER_ID),
        ORDERITEM_ID INT FOREIGN KEY REFERENCES ORDER_ITEM(ORDERITEM_ID),
        USER_ID INT FOREIGN KEY REFERENCES [USER](USER_ID),
        ORDER_TYPE VARCHAR(50),
        TOTAL_WEIGHT DECIMAL(6,2),
        TOTAL_LOAD INT,
        TOTAL_PRICE DECIMAL(10,2),
        QR_CODE TEXT,
        RECEIPT_PATH TEXT,
        ORDER_NOTE TEXT,
        ORDER_STATUS VARCHAR(30),
        PAYMENT_METHOD VARCHAR(30),
        PAYMENT_STATUS VARCHAR(30),
        PICKUP_SCHEDULE DATETIME,
        DATE_CREATED DATETIME DEFAULT GETDATE(),
        DATE_UPDATED DATETIME DEFAULT GETDATE()
    )
    ''')

    # ORDERITEM_DETERGENT (junction table)
    cursor.execute('''
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ORDERITEM_DETERGENT' AND xtype='U')
    CREATE TABLE ORDERITEM_DETERGENT (
        ORDERITEM_ID INT,
        DETERGENT_ID INT,
        PRIMARY KEY (ORDERITEM_ID, DETERGENT_ID),
        FOREIGN KEY (ORDERITEM_ID) REFERENCES ORDER_ITEM(ORDERITEM_ID),
        FOREIGN KEY (DETERGENT_ID) REFERENCES DETERGENT(DETERGENT_ID)
    )
    ''')

    # ORDERITEM_FABCON (junction table)
    cursor.execute('''
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ORDERITEM_FABCON' AND xtype='U')
    CREATE TABLE ORDERITEM_FABCON (
        ORDERITEM_ID INT,
        FABCON_ID INT,
        PRIMARY KEY (ORDERITEM_ID, FABCON_ID),
        FOREIGN KEY (ORDERITEM_ID) REFERENCES ORDER_ITEM(ORDERITEM_ID),
        FOREIGN KEY (FABCON_ID) REFERENCES FABCON(FABCON_ID)
    )
    ''')
    
    # ADMIN_USER table
    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM [USER] WHERE USERNAME='admin')
        INSERT INTO [USER] (USERNAME, PASSWORD, ROLE, FULLNAME, DATE_CREATED)
        VALUES ('admin', 'admin123', 'admin', 'Administrator', GETDATE())
    ''')

    # STAFF_USER table
    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM [USER] WHERE USERNAME='staff')
        INSERT INTO [USER] (USERNAME, PASSWORD, ROLE, FULLNAME, DATE_CREATED)
        VALUES ('staff', 'staff123', 'staff', 'Staff', GETDATE())
    ''')

    conn.commit()
    conn.close()
    print("Database tables initialized successfully.")

def postprocess(sql: str, params: tuple = ()) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"Database error: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def getallprocess(sql: str, params: tuple = ()) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    columns = [column[0] for column in cursor.description]
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return results

# Customner management functions
def add_customer(fullname: str, phone_number: str) -> bool:
    sql = '''
    INSERT INTO CUSTOMER (FULLNAME, PHONE_NUMBER, DATE_CREATED)
    VALUES (?, ?, GETDATE())
    '''
    return postprocess(sql, (fullname, phone_number))

def get_all_customers() -> list:
    sql = "SELECT * FROM CUSTOMER ORDER BY FULLNAME"
    return getallprocess(sql)

def get_customer_by_id(customer_id: int) -> dict:
    sql = "SELECT * FROM CUSTOMER WHERE CUSTOMER_ID=?"
    result = getallprocess(sql, (customer_id,))
    return result[0] if result else None

def update_customer(customer_id: int, fullname: str, phone_number: str) -> bool:
    sql = "UPDATE CUSTOMER SET FULLNAME=?, PHONE_NUMBER=? WHERE CUSTOMER_ID=?"
    return postprocess(sql, (fullname, phone_number, customer_id))

def delete_customer(customer_id: int) -> bool:
    sql = "DELETE FROM CUSTOMER WHERE CUSTOMER_ID=?"
    return postprocess(sql, (customer_id,))

def add_user(username: str, password: str, role: str, fullname: str) -> bool:
    sql = '''
    INSERT INTO [USER] (USERNAME, PASSWORD, ROLE, FULLNAME, DATE_CREATED)
    VALUES (?, ?, ?, ?, GETDATE())
    '''
    return postprocess(sql, (username, password, role, fullname))

# User management functions
def get_all_users() -> list:
    return getallprocess("SELECT * FROM [USER] ORDER BY FULLNAME")

def get_user_by_id(user_id: int) -> dict:
    result = getallprocess("SELECT * FROM [USER] WHERE USER_ID=?", (user_id,))
    return result[0] if result else None

def update_user(user_id: int, username: str, password: str, role: str, fullname: str) -> bool:
    sql = '''
    UPDATE [USER]
    SET USERNAME=?, PASSWORD=?, ROLE=?, FULLNAME=?
    WHERE USER_ID=?
    '''
    return postprocess(sql, (username, password, role, fullname, user_id))

def authenticate_user(username: str, password: str) -> dict:
    sql = "SELECT * FROM [USER] WHERE USERNAME=? AND PASSWORD=?"
    result = getallprocess(sql, (username, password))
    return result[0] if result else None

# Detergent management functions
def add_detergent(name: str, price: float, qty: int, image_filename: str = None) -> bool:
    sql = '''
    INSERT INTO DETERGENT (DETERGENT_NAME, DETERGENT_PRICE, QTY, DATE_CREATED, DATE_UPDATED, IMAGE_FILENAME)
    VALUES (?, ?, ?, GETDATE(), GETDATE(), ?)
    '''
    return postprocess(sql, (name, price, qty, image_filename))

def update_detergent(detergent_id: int, name: str, price: float, qty: int, image_filename: str = None) -> bool:
    sql = '''
    UPDATE DETERGENT
    SET DETERGENT_NAME=?, DETERGENT_PRICE=?, QTY=?, DATE_UPDATED=GETDATE(), IMAGE_FILENAME=?
    WHERE DETERGENT_ID=?
    '''
    return postprocess(sql, (name, price, qty, image_filename, detergent_id))

def delete_detergent(detergent_id: int) -> bool:
    sql = "DELETE FROM DETERGENT WHERE DETERGENT_ID=?"
    return postprocess(sql, (detergent_id,))

def get_all_detergents() -> list:
    sql = 'SELECT * FROM DETERGENT ORDER BY DETERGENT_NAME'
    return getallprocess(sql)

def get_detergent_by_id(detergent_id: int) -> dict:
    sql = "SELECT * FROM DETERGENT WHERE DETERGENT_ID=?"
    result = getallprocess(sql, (detergent_id,))
    return result[0] if result else None

def search_detergents(query: str) -> list:
    sql = """
        SELECT * FROM DETERGENT
        WHERE DETERGENT_NAME LIKE ?
           OR CAST(DETERGENT_ID AS VARCHAR) LIKE ?
        ORDER BY DETERGENT_NAME
    """
    like_query = f'%{query}%'
    return getallprocess(sql, (like_query, like_query))

def get_detergent_total_value() -> dict:
    """Get the total value of detergents (quantity * price)"""
    sql = "EXEC sp_CalculateDetergentTotalValue"
    result = getallprocess(sql)
    return result[0] if result else {'ItemType': 'Detergent', 'TotalValue': 0}

# Fabric Conditioner management functions
def add_fabric_conditioner(name: str, price: float, qty: int, image_filename: str = None) -> bool:
    sql = '''
    INSERT INTO FABCON (FABCON_NAME, FABCON_PRICE, QTY, DATE_CREATED, DATE_UPDATED, IMAGE_FILENAME)
    VALUES (?, ?, ?, GETDATE(), GETDATE(), ?)
    '''
    return postprocess(sql, (name, price, qty, image_filename))

def update_fabric_conditioner(fabric_conditioner_id: int, name: str, price: float, qty: int, image_filename: str = None) -> bool:
    sql = '''
    UPDATE FABCON
    SET FABCON_NAME=?, FABCON_PRICE=?, QTY=?, DATE_UPDATED=GETDATE(), IMAGE_FILENAME=?
    WHERE FABCON_ID=?
    '''
    return postprocess(sql, (name, price, qty, image_filename, fabric_conditioner_id))

def delete_fabric_conditioner(fabric_conditioner_id: int) -> bool:
    sql = "DELETE FROM FABCON WHERE FABCON_ID=?"
    return postprocess(sql, (fabric_conditioner_id,))

def get_all_fabric_conditioners() -> list:
    sql = 'SELECT * FROM FABCON ORDER BY FABCON_NAME'
    return getallprocess(sql)

def get_fabric_conditioner_by_id(fabric_conditioner_id: int) -> dict:
    sql = "SELECT * FROM FABCON WHERE FABCON_ID=?"
    result = getallprocess(sql, (fabric_conditioner_id,))
    return result[0] if result else None

def search_fabric_conditioners(query: str) -> list:
    sql = """
        SELECT * FROM FABCON
        WHERE FABCON_NAME LIKE ?
           OR CAST(FABCON_ID AS VARCHAR) LIKE ?
        ORDER BY FABCON_NAME
    """
    like_query = f'%{query}%'
    return getallprocess(sql, (like_query, like_query))

def get_fabcon_total_value() -> dict:
    """Get the total value of fabric conditioners (quantity * price)"""
    sql = "EXEC sp_CalculateFabconTotalValue"
    result = getallprocess(sql)
    return result[0] if result else {'ItemType': 'Fabric Conditioner', 'TotalValue': 0}
    
if __name__ == "__main__":
    initialize_database()
    print("Connected to SQL Server successfully.")
