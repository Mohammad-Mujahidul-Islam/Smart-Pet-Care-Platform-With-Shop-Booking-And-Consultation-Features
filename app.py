from flask import Flask, render_template, jsonify, request, redirect, url_for
import mysql.connector
from werkzeug.routing import BuildError
from datetime import datetime, timedelta

app = Flask(__name__)

# --- DATABASE CONFIGURATION ---
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '2763',
    'database': 'petnest_db'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

def ensure_discount_schema():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS OfferRedemptions (
            RedemptionID INT AUTO_INCREMENT PRIMARY KEY,
            OfferID INT NOT NULL,
            UserID INT NOT NULL,
            OrderID INT NULL,
            RedeemedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (OfferID) REFERENCES Offers(OfferID) ON DELETE CASCADE,
            FOREIGN KEY (UserID) REFERENCES Users(UserID) ON DELETE CASCADE,
            FOREIGN KEY (OrderID) REFERENCES Orders(OrderID) ON DELETE SET NULL
        )
    """)

    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'Offers'
        """,
        (db_config['database'],)
    )
    existing = {row['COLUMN_NAME'] for row in cursor.fetchall()}

    alters = []
    if 'AppliesToCategory' not in existing:
        alters.append("ADD COLUMN AppliesToCategory VARCHAR(50) NULL")
    if 'MaxUsesPerUser' not in existing:
        alters.append("ADD COLUMN MaxUsesPerUser INT NULL")
    if 'MaxTotalUses' not in existing:
        alters.append("ADD COLUMN MaxTotalUses INT NULL")

    if alters:
        cursor.execute(f"ALTER TABLE Offers {', '.join(alters)}")

    # Keep NEST20 one-time per user globally.
    cursor.execute(
        "UPDATE Offers SET MaxUsesPerUser = 1, TargetUserID = NULL WHERE OfferCode = 'NEST20'"
    )

    conn.commit()
    cursor.close()
    conn.close()

def get_home_banner_offer(user_id=None):
    ensure_discount_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT OfferID, OfferCode, DiscountPercent, AppliesToCategory, MaxUsesPerUser, MaxTotalUses
        FROM Offers
        WHERE ValidFrom <= NOW()
          AND ValidUntil >= NOW()
          AND (%s IS NULL AND TargetUserID IS NULL OR %s IS NOT NULL AND (TargetUserID IS NULL OR TargetUserID = %s))
        ORDER BY DiscountPercent DESC, OfferID DESC
        """,
        (user_id, user_id, user_id)
    )
    offers = cursor.fetchall()

    for offer in offers:
        cursor.execute("SELECT COUNT(*) AS Cnt FROM OfferRedemptions WHERE OfferID = %s", (offer['OfferID'],))
        total_used = int((cursor.fetchone() or {}).get('Cnt') or 0)
        if offer.get('MaxTotalUses') is not None and total_used >= int(offer['MaxTotalUses']):
            continue

        if user_id is not None:
            cursor.execute(
                "SELECT COUNT(*) AS Cnt FROM OfferRedemptions WHERE OfferID = %s AND UserID = %s",
                (offer['OfferID'], user_id)
            )
            used_by_user = int((cursor.fetchone() or {}).get('Cnt') or 0)
            if offer.get('MaxUsesPerUser') is not None and used_by_user >= int(offer['MaxUsesPerUser']):
                continue

        cursor.close()
        conn.close()
        return offer

    cursor.close()
    conn.close()
    return None

def ensure_vet_services_schema():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS VetServices (
            ServiceID INT AUTO_INCREMENT PRIMARY KEY,
            VetID INT NOT NULL,
            ServiceName VARCHAR(150) NOT NULL,
            PetCategory VARCHAR(50) NULL,
            Description TEXT NOT NULL,
            Price DECIMAL(10,2) NOT NULL DEFAULT 0.00,
            DurationMinutes INT NOT NULL DEFAULT 30,
            IsActive TINYINT(1) NOT NULL DEFAULT 1,
            CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (VetID) REFERENCES Users(UserID) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'VetServices'
        """,
        (db_config['database'],)
    )
    columns = {row['COLUMN_NAME'] for row in cursor.fetchall()}
    if 'DurationMinutes' not in columns:
        cursor.execute("ALTER TABLE VetServices ADD COLUMN DurationMinutes INT NOT NULL DEFAULT 30")
    conn.commit()
    cursor.close()
    conn.close()

def ensure_vet_booking_schema():
    ensure_vet_services_schema()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS VetAvailability (
            VetID INT PRIMARY KEY,
            StartTime TIME NOT NULL DEFAULT '09:00:00',
            EndTime TIME NOT NULL DEFAULT '20:00:00',
            FOREIGN KEY (VetID) REFERENCES Users(UserID) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS VetAppointments (
            AppointmentID INT AUTO_INCREMENT PRIMARY KEY,
            VetID INT NOT NULL,
            CustomerID INT NOT NULL,
            ServiceID INT NOT NULL,
            AppointmentDate DATE NOT NULL,
            SerialNo INT NOT NULL,
            SlotStart TIME NOT NULL,
            SlotEnd TIME NOT NULL,
            Status VARCHAR(20) NOT NULL DEFAULT 'Booked',
            CustomerNote TEXT NULL,
            CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (VetID) REFERENCES Users(UserID) ON DELETE CASCADE,
            FOREIGN KEY (CustomerID) REFERENCES Users(UserID) ON DELETE CASCADE,
            FOREIGN KEY (ServiceID) REFERENCES VetServices(ServiceID) ON DELETE CASCADE,
            UNIQUE KEY uq_vet_date_serial (VetID, AppointmentDate, SerialNo)
        )
        """
    )
    conn.commit()
    cursor.close()
    conn.close()

def allocate_vet_slot(conn, vet_id, service_id, customer_id, preferred_date, note):
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT ServiceID, ServiceName, DurationMinutes FROM VetServices WHERE ServiceID = %s AND VetID = %s AND IsActive = 1 LIMIT 1",
        (service_id, vet_id)
    )
    service = cursor.fetchone()
    if not service:
        cursor.close()
        return None, "Service unavailable."

    duration = max(5, int(service.get('DurationMinutes') or 30))
    cursor.execute("SELECT StartTime, EndTime FROM VetAvailability WHERE VetID = %s", (vet_id,))
    availability = cursor.fetchone()
    if not availability:
        cursor.execute("INSERT INTO VetAvailability (VetID, StartTime, EndTime) VALUES (%s, '09:00:00', '20:00:00')", (vet_id,))
        conn.commit()
        start_time = datetime.strptime("09:00:00", "%H:%M:%S").time()
        end_time = datetime.strptime("20:00:00", "%H:%M:%S").time()
    else:
        start_time = availability['StartTime']
        end_time = availability['EndTime']

    if isinstance(start_time, timedelta):
        start_time = (datetime.min + start_time).time()
    if isinstance(end_time, timedelta):
        end_time = (datetime.min + end_time).time()

    preferred = datetime.strptime(preferred_date, "%Y-%m-%d").date() if preferred_date else datetime.now().date()
    daily_minutes = int((datetime.combine(datetime.min, end_time) - datetime.combine(datetime.min, start_time)).total_seconds() // 60)
    total_slots = max(1, daily_minutes // duration)

    slot_result = None
    for offset in range(0, 45):
        appt_date = preferred + timedelta(days=offset)
        cursor.execute(
            """
            SELECT COUNT(*) AS Cnt
            FROM VetAppointments
            WHERE VetID = %s AND AppointmentDate = %s AND Status <> 'Cancelled'
            """,
            (vet_id, appt_date)
        )
        used = int(cursor.fetchone()['Cnt'])
        if used >= total_slots:
            continue

        serial_no = used + 1
        slot_start_dt = datetime.combine(appt_date, start_time) + timedelta(minutes=(serial_no - 1) * duration)
        slot_end_dt = slot_start_dt + timedelta(minutes=duration)
        slot_result = {
            'appointment_date': appt_date,
            'serial_no': serial_no,
            'slot_start_dt': slot_start_dt,
            'slot_end_dt': slot_end_dt
        }
        break

    if slot_result:
        cursor.execute(
            """
            INSERT INTO VetAppointments (VetID, CustomerID, ServiceID, AppointmentDate, SerialNo, SlotStart, SlotEnd, CustomerNote)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                vet_id, customer_id, service_id,
                slot_result['appointment_date'], slot_result['serial_no'],
                slot_result['slot_start_dt'].time(), slot_result['slot_end_dt'].time(),
                note or None
            )
        )
        appointment_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        return {
            'appointment_id': appointment_id,
            'appointment_date': str(slot_result['appointment_date']),
            'serial_no': slot_result['serial_no'],
            'slot_start': slot_result['slot_start_dt'].strftime("%I:%M %p"),
            'slot_end': slot_result['slot_end_dt'].strftime("%I:%M %p"),
            'service_name': service['ServiceName']
        }, None

    cursor.close()
    return None, "No slot available in next 45 days."

def preview_next_vet_slot(conn, vet_id, service_id):
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT DurationMinutes FROM VetServices WHERE ServiceID = %s AND VetID = %s AND IsActive = 1 LIMIT 1",
        (service_id, vet_id)
    )
    service = cursor.fetchone()
    if not service:
        cursor.close()
        return None
    duration = max(5, int(service.get('DurationMinutes') or 30))

    cursor.execute("SELECT StartTime, EndTime FROM VetAvailability WHERE VetID = %s", (vet_id,))
    availability = cursor.fetchone()
    start_time = availability['StartTime'] if availability else datetime.strptime("09:00:00", "%H:%M:%S").time()
    end_time = availability['EndTime'] if availability else datetime.strptime("20:00:00", "%H:%M:%S").time()

    if isinstance(start_time, timedelta):
        start_time = (datetime.min + start_time).time()
    if isinstance(end_time, timedelta):
        end_time = (datetime.min + end_time).time()

    daily_minutes = int((datetime.combine(datetime.min, end_time) - datetime.combine(datetime.min, start_time)).total_seconds() // 60)
    total_slots = max(1, daily_minutes // duration)
    today = datetime.now().date()

    for offset in range(0, 45):
        appt_date = today + timedelta(days=offset)
        cursor.execute(
            """
            SELECT COUNT(*) AS Cnt
            FROM VetAppointments
            WHERE VetID = %s AND AppointmentDate = %s AND Status <> 'Cancelled'
            """,
            (vet_id, appt_date)
        )
        used = int(cursor.fetchone()['Cnt'])
        if used >= total_slots:
            continue
        serial_no = used + 1
        slot_start_dt = datetime.combine(appt_date, start_time) + timedelta(minutes=(serial_no - 1) * duration)
        slot_end_dt = slot_start_dt + timedelta(minutes=duration)
        cursor.close()
        return {
            'appointment_date': str(appt_date),
            'serial_no': serial_no,
            'slot_start': slot_start_dt.strftime("%I:%M %p"),
            'slot_end': slot_end_dt.strftime("%I:%M %p"),
        }
    cursor.close()
    return None


# ---- Service provider businesses (grooming, daycare, training, etc.) ----

PROVIDER_DEMO_CATALOG = [
    ("Grooming", "Glossy Paws Grooming", "Dog, Cat", "spdemo.grooming@petnest.local"),
    ("Pet Daycare", "Sunny Paws Daycare", "Dog", "spdemo.daycare@petnest.local"),
    ("Training", "Obedience Pro Training", "Dog", "spdemo.training@petnest.local"),
    ("Boarding", "Cozy Tails Boarding", "Dog, Cat", "spdemo.boarding@petnest.local"),
    ("Dog Walking", "Stride Pals Walking", "Dog", "spdemo.walking@petnest.local"),
    ("Pet Sitting", "Trusty Home Sitting", "Cat, Small Pet", "spdemo.sitting@petnest.local"),
    ("Pet Photography", "FurryFrame Studio", "All pets", "spdemo.photo@petnest.local"),
    ("Pet Transport", "PetMove Express", "Dog, Cat", "spdemo.transport@petnest.local"),
    ("Pet Spa", "Lavish Tails Spa", "Dog, Cat", "spdemo.spa@petnest.local"),
    ("Aquatic Care", "Fin & Scale Aquatics", "Fish, Reptilian", "spdemo.aquatic@petnest.local"),
]


def ensure_service_provider_business_schema():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ProviderServices (
            ServiceID INT AUTO_INCREMENT PRIMARY KEY,
            ProviderID INT NOT NULL,
            ServiceName VARCHAR(150) NOT NULL,
            PetCategory VARCHAR(50) NULL,
            Description TEXT NOT NULL,
            Price DECIMAL(10,2) NOT NULL DEFAULT 0.00,
            DurationMinutes INT NOT NULL DEFAULT 30,
            IsActive TINYINT(1) NOT NULL DEFAULT 1,
            CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ProviderID) REFERENCES Users(UserID) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ProviderAvailability (
            ProviderID INT PRIMARY KEY,
            StartTime TIME NOT NULL DEFAULT '09:00:00',
            EndTime TIME NOT NULL DEFAULT '20:00:00',
            FOREIGN KEY (ProviderID) REFERENCES Users(UserID) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ProviderAppointments (
            AppointmentID INT AUTO_INCREMENT PRIMARY KEY,
            ProviderID INT NOT NULL,
            CustomerID INT NOT NULL,
            ServiceID INT NOT NULL,
            AppointmentDate DATE NOT NULL,
            SerialNo INT NOT NULL,
            SlotStart TIME NOT NULL,
            SlotEnd TIME NOT NULL,
            Status VARCHAR(20) NOT NULL DEFAULT 'Booked',
            CustomerNote TEXT NULL,
            CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ProviderID) REFERENCES Users(UserID) ON DELETE CASCADE,
            FOREIGN KEY (CustomerID) REFERENCES Users(UserID) ON DELETE CASCADE,
            FOREIGN KEY (ServiceID) REFERENCES ProviderServices(ServiceID) ON DELETE CASCADE,
            UNIQUE KEY uq_provider_date_serial (ProviderID, AppointmentDate, SerialNo)
        )
        """
    )
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'ServiceProviderProfiles'
        """,
        (db_config['database'],),
    )
    cols = {row['COLUMN_NAME'] for row in cursor.fetchall()}
    if cols and 'AnimalExpertise' not in cols:
        cursor.execute("ALTER TABLE ServiceProviderProfiles ADD COLUMN AnimalExpertise VARCHAR(100) NULL")
    cursor.close()
    conn.commit()
    conn.close()
    seed_demo_service_providers()


def seed_demo_service_providers():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    for service_type, biz, expertise, email in PROVIDER_DEMO_CATALOG:
        cursor.execute("SELECT UserID FROM Users WHERE Email = %s", (email,))
        if cursor.fetchone():
            continue
        cursor.execute(
            """
            INSERT INTO Users (Name, Email, Phone, Password, Role, AccountStatus)
            VALUES (%s, %s, %s, %s, 'ServiceProvider', 'Active')
            """,
            (biz, email, "01700000000", "pass123"),
        )
        uid = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO ServiceProviderProfiles (UserID, BusinessName, ServiceType, Location, Description, AnimalExpertise)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                uid,
                biz,
                service_type,
                "Dhaka, Bangladesh",
                f"PetNest demo {service_type.lower()} for {expertise}.",
                expertise,
            ),
        )
        cursor.execute(
            """
            INSERT INTO ProviderServices (ProviderID, ServiceName, PetCategory, Description, Price, DurationMinutes, IsActive)
            VALUES (%s, %s, %s, %s, %s, 45, 1)
            """,
            (
                uid,
                f"Standard {service_type}",
                None,
                f"Bookable service — {expertise}.",
                25.0 + (uid % 10),
            ),
        )
        cursor.execute(
            "INSERT INTO ProviderAvailability (ProviderID, StartTime, EndTime) VALUES (%s, '09:00:00', '20:00:00')",
            (uid,),
        )
    conn.commit()
    cursor.close()
    conn.close()


def allocate_provider_slot(conn, provider_id, service_id, customer_id, preferred_date, note):
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT ServiceID, ServiceName, DurationMinutes FROM ProviderServices WHERE ServiceID = %s AND ProviderID = %s AND IsActive = 1 LIMIT 1",
        (service_id, provider_id)
    )
    service = cursor.fetchone()
    if not service:
        cursor.close()
        return None, "Service unavailable."

    duration = max(5, int(service.get('DurationMinutes') or 30))
    cursor.execute("SELECT StartTime, EndTime FROM ProviderAvailability WHERE ProviderID = %s", (provider_id,))
    availability = cursor.fetchone()
    if not availability:
        cursor.execute("INSERT INTO ProviderAvailability (ProviderID, StartTime, EndTime) VALUES (%s, '09:00:00', '20:00:00')", (provider_id,))
        conn.commit()
        start_time = datetime.strptime("09:00:00", "%H:%M:%S").time()
        end_time = datetime.strptime("20:00:00", "%H:%M:%S").time()
    else:
        start_time = availability['StartTime']
        end_time = availability['EndTime']

    if isinstance(start_time, timedelta):
        start_time = (datetime.min + start_time).time()
    if isinstance(end_time, timedelta):
        end_time = (datetime.min + end_time).time()

    preferred = datetime.strptime(preferred_date, "%Y-%m-%d").date() if preferred_date else datetime.now().date()
    daily_minutes = int((datetime.combine(datetime.min, end_time) - datetime.combine(datetime.min, start_time)).total_seconds() // 60)
    total_slots = max(1, daily_minutes // duration)

    slot_result = None
    for offset in range(0, 45):
        appt_date = preferred + timedelta(days=offset)
        cursor.execute(
            """
            SELECT COUNT(*) AS Cnt
            FROM ProviderAppointments
            WHERE ProviderID = %s AND AppointmentDate = %s AND Status <> 'Cancelled'
            """,
            (provider_id, appt_date)
        )
        used = int(cursor.fetchone()['Cnt'])
        if used >= total_slots:
            continue

        serial_no = used + 1
        slot_start_dt = datetime.combine(appt_date, start_time) + timedelta(minutes=(serial_no - 1) * duration)
        slot_end_dt = slot_start_dt + timedelta(minutes=duration)
        slot_result = {
            'appointment_date': appt_date,
            'serial_no': serial_no,
            'slot_start_dt': slot_start_dt,
            'slot_end_dt': slot_end_dt
        }
        break

    if slot_result:
        cursor.execute(
            """
            INSERT INTO ProviderAppointments (ProviderID, CustomerID, ServiceID, AppointmentDate, SerialNo, SlotStart, SlotEnd, CustomerNote)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                provider_id, customer_id, service_id,
                slot_result['appointment_date'], slot_result['serial_no'],
                slot_result['slot_start_dt'].time(), slot_result['slot_end_dt'].time(),
                note or None
            )
        )
        appointment_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        return {
            'appointment_id': appointment_id,
            'appointment_date': str(slot_result['appointment_date']),
            'serial_no': slot_result['serial_no'],
            'slot_start': slot_result['slot_start_dt'].strftime("%I:%M %p"),
            'slot_end': slot_result['slot_end_dt'].strftime("%I:%M %p"),
            'service_name': service['ServiceName']
        }, None

    cursor.close()
    return None, "No slot available in next 45 days."


def preview_next_provider_slot(conn, provider_id, service_id):
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT DurationMinutes FROM ProviderServices WHERE ServiceID = %s AND ProviderID = %s AND IsActive = 1 LIMIT 1",
        (service_id, provider_id)
    )
    service = cursor.fetchone()
    if not service:
        cursor.close()
        return None
    duration = max(5, int(service.get('DurationMinutes') or 30))

    cursor.execute("SELECT StartTime, EndTime FROM ProviderAvailability WHERE ProviderID = %s", (provider_id,))
    availability = cursor.fetchone()
    start_time = availability['StartTime'] if availability else datetime.strptime("09:00:00", "%H:%M:%S").time()
    end_time = availability['EndTime'] if availability else datetime.strptime("20:00:00", "%H:%M:%S").time()

    if isinstance(start_time, timedelta):
        start_time = (datetime.min + start_time).time()
    if isinstance(end_time, timedelta):
        end_time = (datetime.min + end_time).time()

    daily_minutes = int((datetime.combine(datetime.min, end_time) - datetime.combine(datetime.min, start_time)).total_seconds() // 60)
    total_slots = max(1, daily_minutes // duration)
    today = datetime.now().date()

    for offset in range(0, 45):
        appt_date = today + timedelta(days=offset)
        cursor.execute(
            """
            SELECT COUNT(*) AS Cnt
            FROM ProviderAppointments
            WHERE ProviderID = %s AND AppointmentDate = %s AND Status <> 'Cancelled'
            """,
            (provider_id, appt_date)
        )
        used = int(cursor.fetchone()['Cnt'])
        if used >= total_slots:
            continue
        serial_no = used + 1
        slot_start_dt = datetime.combine(appt_date, start_time) + timedelta(minutes=(serial_no - 1) * duration)
        slot_end_dt = slot_start_dt + timedelta(minutes=duration)
        cursor.close()
        return {
            'appointment_date': str(appt_date),
            'serial_no': serial_no,
            'slot_start': slot_start_dt.strftime("%I:%M %p"),
            'slot_end': slot_end_dt.strftime("%I:%M %p"),
        }
    cursor.close()
    return None

try:
    from admin import admin_bp
    app.register_blueprint(admin_bp)
except Exception:
    # Keep app startup resilient if admin blueprint is unavailable.
    pass

# Optional role-specific blueprints. These modules can provide additional
# workflows per role (seller/service provider/vet) when available.
for module_name, blueprint_name in (
    ("seller", "seller_bp"),
    ("service", "service_provider_bp"),
    ("vet", "vet_bp"),
):
    try:
        module = __import__(module_name, fromlist=[blueprint_name])
        app.register_blueprint(getattr(module, blueprint_name))
    except Exception:
        # Keep app startup resilient when optional modules are missing
        # or use an incompatible storage backend.
        pass

# ==========================================
# 1. NAVIGATION ROUTES
# ==========================================

@app.route('/')
def home():
    # Standard homepage for guests
    offer = get_home_banner_offer(user_id=None)
    return render_template('index.html', username=None, user_id=None, role=None, home_offer=offer)

@app.route('/user/<int:user_id>')
def customer_home(user_id):
    # Homepage for logged-in users
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if user:
        role = (user.get('Role') or '').strip()
        role_endpoints = {
            'Admin': ('admin.admin_dashboard', {'user_id': user_id}),
            'Seller': ('seller.seller_dashboard', {'user_id': user_id}),
            'ServiceProvider': ('provider_services_manager', {'user_id': user_id}),
            'Vet': ('vet.vet_dashboard', {'user_id': user_id}),
        }
        if role in role_endpoints:
            endpoint, values = role_endpoints[role]
            try:
                return redirect(url_for(endpoint, **values))
            except BuildError:
                # If optional blueprint/route is unavailable, fall back to customer home.
                pass
        offer = get_home_banner_offer(user_id=user_id)
        return render_template('index.html', username=user['Name'], user_id=user_id, role=role, home_offer=offer)
    return "User not found", 404

@app.route('/user/<int:user_id>/seller/dashboard')
def seller_portal(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user.get('Role') != 'Seller':
        cursor.close()
        conn.close()
        return "Access Denied", 403

    cursor.execute(
        """
        SELECT ProductID, Name, PetCategory, Price, StockQuantity, Status
        FROM Products
        WHERE SellerID = %s
        ORDER BY ProductID DESC
        """,
        (user_id,)
    )
    products = cursor.fetchall()

    cursor.execute(
        """
        SELECT
            COALESCE(SUM(oi.Quantity), 0) AS UnitsSold,
            COALESCE(SUM(oi.Quantity * oi.PriceAtPurchase), 0) AS GrossRevenue,
            COUNT(DISTINCT o.OrderID) AS TotalOrders
        FROM OrderItems oi
        JOIN Products p ON p.ProductID = oi.ProductID
        JOIN Orders o ON o.OrderID = oi.OrderID
        WHERE p.SellerID = %s
        """,
        (user_id,)
    )
    summary = cursor.fetchone() or {}

    cursor.execute(
        """
        SELECT
            o.OrderID,
            o.OrderDate,
            o.OrderStatus,
            p.Name AS ProductName,
            oi.Quantity,
            oi.PriceAtPurchase,
            ROUND(oi.Quantity * oi.PriceAtPurchase, 2) AS LineTotal
        FROM OrderItems oi
        JOIN Orders o ON o.OrderID = oi.OrderID
        JOIN Products p ON p.ProductID = oi.ProductID
        WHERE p.SellerID = %s
        ORDER BY o.OrderDate DESC, o.OrderID DESC
        LIMIT 200
        """,
        (user_id,)
    )
    sales_details = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'seller_portal.html',
        user=user,
        user_id=user_id,
        products=products,
        sales_details=sales_details,
        units_sold=int(summary.get('UnitsSold') or 0),
        gross_revenue=round(float(summary.get('GrossRevenue') or 0), 2),
        total_orders=int(summary.get('TotalOrders') or 0),
    )

@app.route('/user/<int:user_id>/seller/add-product', methods=['POST'])
def seller_add_product(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user.get('Role') != 'Seller':
        cursor.close()
        conn.close()
        return "Access Denied", 403

    name = (request.form.get('name') or '').strip()
    pet_category = (request.form.get('pet_category') or 'General').strip()
    product_category = (request.form.get('product_category') or 'General').strip()
    description = (request.form.get('description') or '').strip()
    price_raw = (request.form.get('price') or '').strip()
    stock_raw = (request.form.get('stock_quantity') or '').strip()

    try:
        price = round(float(price_raw), 2)
        stock = int(stock_raw)
    except (TypeError, ValueError):
        cursor.close()
        conn.close()
        return "Invalid price or stock value.", 400

    if not name or price < 0 or stock < 0:
        cursor.close()
        conn.close()
        return "Invalid product input.", 400

    raw_cursor = conn.cursor()
    raw_cursor.execute(
        """
        INSERT INTO Products (SellerID, Name, PetCategory, ProductCategory, Description, Price, StockQuantity, Status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending')
        """,
        (user_id, name, pet_category, product_category, description, price, stock)
    )
    product_id = raw_cursor.lastrowid

    # Notify all active admins that a seller submitted a product for approval.
    raw_cursor.execute("SELECT UserID FROM Users WHERE Role = 'Admin' AND AccountStatus = 'Active'")
    admins = raw_cursor.fetchall()
    for admin in admins:
        raw_cursor.execute(
            "INSERT INTO Notifications (UserID, Message) VALUES (%s, %s)",
            (admin[0], f"Seller #{user_id} submitted product #{product_id}: {name}. Approval required.")
        )
    conn.commit()
    raw_cursor.close()
    cursor.close()
    conn.close()
    return redirect(url_for('seller_portal', user_id=user_id))

@app.route('/user/<int:user_id>/seller/restock', methods=['POST'])
def seller_restock_product(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user.get('Role') != 'Seller':
        cursor.close()
        conn.close()
        return "Access Denied", 403

    product_id_raw = (request.form.get('product_id') or '').strip()
    qty_raw = (request.form.get('restock_quantity') or '').strip()
    if not product_id_raw.isdigit():
        cursor.close()
        conn.close()
        return "Invalid product id.", 400

    try:
        restock_qty = int(qty_raw)
    except (TypeError, ValueError):
        cursor.close()
        conn.close()
        return "Invalid restock quantity.", 400

    if restock_qty <= 0:
        cursor.close()
        conn.close()
        return "Restock quantity must be greater than zero.", 400

    product_id = int(product_id_raw)
    cursor.execute(
        "SELECT ProductID FROM Products WHERE ProductID = %s AND SellerID = %s",
        (product_id, user_id)
    )
    product = cursor.fetchone()
    if not product:
        cursor.close()
        conn.close()
        return "Product not found for this seller.", 404

    raw_cursor = conn.cursor()
    raw_cursor.execute(
        "UPDATE Products SET StockQuantity = StockQuantity + %s WHERE ProductID = %s AND SellerID = %s",
        (restock_qty, product_id, user_id)
    )
    conn.commit()
    raw_cursor.close()
    cursor.close()
    conn.close()
    return redirect(url_for('seller_portal', user_id=user_id))

@app.route('/browse')
def browse():
    return render_template('browse.html', username=None, user_id=None, role=None)

@app.route('/user/<int:user_id>/browse')
def user_browse(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if not user:
        return "User not found", 404
    return render_template('browse.html', username=user['Name'], user_id=user_id, role=user['Role'])

@app.route('/vets')
def browse_vets():
    ensure_vet_services_schema()
    pet_type = (request.args.get('pet_type') or '').strip()
    expertise = (request.args.get('expertise') or '').strip()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    sql = """
        SELECT u.UserID, u.Name, u.AccountStatus, u.Phone, v.ClinicName, v.Specialization, v.ExperienceYears, v.ConsultationFee,
               GROUP_CONCAT(DISTINCT CONCAT(vs.ServiceName, ' (', COALESCE(vs.PetCategory, 'All'), ') - $', FORMAT(vs.Price, 2)) SEPARATOR ' || ') AS ServiceList
        FROM Users u
        JOIN Vets v ON u.UserID = v.UserID
        LEFT JOIN VetServices vs ON vs.VetID = u.UserID AND vs.IsActive = 1
        WHERE u.Role = 'Vet' AND u.AccountStatus = 'Active'
    """
    params = []
    if expertise:
        sql += " AND (v.Specialization LIKE %s OR v.ClinicName LIKE %s OR vs.ServiceName LIKE %s OR vs.Description LIKE %s)"
        params.extend([f"%{expertise}%", f"%{expertise}%", f"%{expertise}%", f"%{expertise}%"])
    if pet_type:
        sql += " AND (v.Specialization LIKE %s OR vs.PetCategory = %s)"
        params.extend([f"%{pet_type}%", pet_type])
    sql += " GROUP BY u.UserID, u.Name, u.AccountStatus, u.Phone, v.ClinicName, v.Specialization, v.ExperienceYears, v.ConsultationFee ORDER BY v.ExperienceYears DESC, u.UserID DESC"

    cursor.execute(sql, tuple(params))
    vets = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('vet_browser.html', username=None, user_id=None, role=None, vets=vets, pet_type=pet_type, expertise=expertise)

@app.route('/user/<int:user_id>/vets')
def user_browse_vets(user_id):
    ensure_vet_services_schema()
    pet_type = (request.args.get('pet_type') or '').strip()
    expertise = (request.args.get('expertise') or '').strip()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.close()
        conn.close()
        return "User not found", 404

    sql = """
        SELECT u.UserID, u.Name, u.AccountStatus, u.Phone, v.ClinicName, v.Specialization, v.ExperienceYears, v.ConsultationFee,
               GROUP_CONCAT(DISTINCT CONCAT(vs.ServiceName, ' (', COALESCE(vs.PetCategory, 'All'), ') - $', FORMAT(vs.Price, 2)) SEPARATOR ' || ') AS ServiceList
        FROM Users u
        JOIN Vets v ON u.UserID = v.UserID
        LEFT JOIN VetServices vs ON vs.VetID = u.UserID AND vs.IsActive = 1
        WHERE u.Role = 'Vet' AND u.AccountStatus = 'Active'
    """
    params = []
    if expertise:
        sql += " AND (v.Specialization LIKE %s OR v.ClinicName LIKE %s OR vs.ServiceName LIKE %s OR vs.Description LIKE %s)"
        params.extend([f"%{expertise}%", f"%{expertise}%", f"%{expertise}%", f"%{expertise}%"])
    if pet_type:
        sql += " AND (v.Specialization LIKE %s OR vs.PetCategory = %s)"
        params.extend([f"%{pet_type}%", pet_type])
    sql += " GROUP BY u.UserID, u.Name, u.AccountStatus, u.Phone, v.ClinicName, v.Specialization, v.ExperienceYears, v.ConsultationFee ORDER BY v.ExperienceYears DESC, u.UserID DESC"

    cursor.execute(sql, tuple(params))
    vets = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('vet_browser.html', username=user['Name'], user_id=user_id, role=user['Role'], vets=vets, pet_type=pet_type, expertise=expertise)

def _load_service_provider_directory(pet_type, expertise, service_type):
    ensure_service_provider_business_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    sql = """
        SELECT u.UserID, u.Name, u.AccountStatus, u.Phone,
               p.BusinessName, p.ServiceType, p.AnimalExpertise, p.Location, p.Description,
               GROUP_CONCAT(DISTINCT CONCAT(ps.ServiceName, ' (', COALESCE(ps.PetCategory, 'All'), ') - $', FORMAT(ps.Price, 2)) SEPARATOR ' || ') AS ServiceList
        FROM Users u
        JOIN ServiceProviderProfiles p ON p.UserID = u.UserID
        LEFT JOIN ProviderServices ps ON ps.ProviderID = u.UserID AND ps.IsActive = 1
        WHERE u.Role = 'ServiceProvider' AND u.AccountStatus = 'Active'
    """
    params = []
    if expertise:
        sql += " AND (p.BusinessName LIKE %s OR p.Description LIKE %s OR ps.ServiceName LIKE %s OR ps.Description LIKE %s OR p.ServiceType LIKE %s OR p.AnimalExpertise LIKE %s)"
        w = f"%{expertise}%"
        params.extend([w, w, w, w, w, w])
    if service_type:
        sql += " AND p.ServiceType LIKE %s"
        params.append(f"%{service_type}%")
    if pet_type:
        sql += " AND (p.AnimalExpertise LIKE %s OR p.AnimalExpertise LIKE %s OR ps.PetCategory = %s)"
        params.extend([f"%{pet_type}%", "%All pets%", pet_type])
    sql += (
        " GROUP BY u.UserID, u.Name, u.AccountStatus, u.Phone, p.BusinessName, p.ServiceType, "
        "p.AnimalExpertise, p.Location, p.Description ORDER BY p.BusinessName ASC, u.UserID DESC"
    )
    cursor.execute(sql, tuple(params))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


@app.route('/service-providers')
def browse_service_providers():
    pet_type = (request.args.get('pet_type') or '').strip()
    expertise = (request.args.get('expertise') or '').strip()
    service_type = (request.args.get('service_type') or '').strip()
    providers = _load_service_provider_directory(pet_type, expertise, service_type)
    provider_types = sorted({c[0] for c in PROVIDER_DEMO_CATALOG})
    return render_template(
        'service_provider_browser.html',
        username=None, user_id=None, role=None,
        providers=providers, pet_type=pet_type, expertise=expertise, service_type=service_type,
        provider_types=provider_types
    )


@app.route('/user/<int:user_id>/service-providers')
def user_browse_service_providers(user_id):
    pet_type = (request.args.get('pet_type') or '').strip()
    expertise = (request.args.get('expertise') or '').strip()
    service_type = (request.args.get('service_type') or '').strip()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if not user:
        return "User not found", 404
    providers = _load_service_provider_directory(pet_type, expertise, service_type)
    provider_types = sorted({c[0] for c in PROVIDER_DEMO_CATALOG})
    return render_template(
        'service_provider_browser.html',
        username=user['Name'], user_id=user_id, role=user['Role'],
        providers=providers, pet_type=pet_type, expertise=expertise, service_type=service_type,
        provider_types=provider_types
    )


@app.route('/user/<int:user_id>/vet/services')
def vet_services_manager(user_id):
    ensure_vet_services_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user.get('Role') != 'Vet':
        cursor.close()
        conn.close()
        return "Access Denied", 403

    cursor.execute(
        """
        SELECT ServiceID, ServiceName, PetCategory, Description, Price, DurationMinutes, IsActive, CreatedAt
        FROM VetServices
        WHERE VetID = %s
        ORDER BY ServiceID DESC
        """,
        (user_id,)
    )
    services = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('vet_services_manage.html', user=user, user_id=user_id, services=services)

@app.route('/user/<int:user_id>/vet/appointments')
def vet_appointments_manager(user_id):
    ensure_vet_booking_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user.get('Role') != 'Vet':
        cursor.close()
        conn.close()
        return "Access Denied", 403

    cursor.execute(
        """
        SELECT va.AppointmentID, va.AppointmentDate, va.SerialNo, va.SlotStart, va.SlotEnd, va.Status, va.CustomerNote,
               c.Name AS CustomerName, c.Phone AS CustomerPhone, vs.ServiceName
        FROM VetAppointments va
        JOIN Users c ON c.UserID = va.CustomerID
        JOIN VetServices vs ON vs.ServiceID = va.ServiceID
        WHERE va.VetID = %s
        ORDER BY va.AppointmentDate DESC, va.SerialNo ASC
        """,
        (user_id,)
    )
    appointments = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('vet_appointments_manage.html', user=user, user_id=user_id, appointments=appointments)

@app.route('/user/<int:user_id>/vet/appointments/<int:appointment_id>/complete', methods=['POST'])
def vet_appointment_complete(user_id, appointment_id):
    ensure_vet_booking_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user.get('Role') != 'Vet':
        cursor.close()
        conn.close()
        return "Access Denied", 403

    cursor.execute(
        """
        UPDATE VetAppointments
        SET Status = 'Completed'
        WHERE AppointmentID = %s AND VetID = %s AND Status NOT IN ('Completed', 'Cancelled')
        """,
        (appointment_id, user_id),
    )
    conn.commit()
    updated = cursor.rowcount
    cursor.close()
    conn.close()
    if not updated:
        return "Appointment not found or cannot be completed", 404
    return redirect(url_for('vet_appointments_manager', user_id=user_id))

@app.route('/user/<int:user_id>/vet/services/add', methods=['POST'])
def vet_services_add(user_id):
    ensure_vet_services_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user.get('Role') != 'Vet':
        cursor.close()
        conn.close()
        return "Access Denied", 403

    service_name = (request.form.get('service_name') or '').strip()
    pet_category = (request.form.get('pet_category') or '').strip() or None
    description = (request.form.get('description') or '').strip()
    price_raw = (request.form.get('price') or '').strip()
    duration_raw = (request.form.get('duration_minutes') or '').strip()

    try:
        price = round(float(price_raw), 2)
        duration = int(duration_raw)
    except (TypeError, ValueError):
        cursor.close()
        conn.close()
        return "Invalid fee or duration value.", 400

    if not service_name or not description or price < 0 or duration <= 0:
        cursor.close()
        conn.close()
        return "Invalid service input.", 400

    raw_cursor = conn.cursor()
    raw_cursor.execute("SELECT ServiceID FROM VetServices WHERE VetID = %s ORDER BY ServiceID ASC LIMIT 1", (user_id,))
    existing = raw_cursor.fetchone()
    if existing:
        raw_cursor.execute(
            """
            UPDATE VetServices
            SET ServiceName = %s, PetCategory = %s, Description = %s, Price = %s, DurationMinutes = %s, IsActive = 1
            WHERE ServiceID = %s AND VetID = %s
            """,
            (service_name, pet_category, description, price, duration, existing[0], user_id)
        )
    else:
        raw_cursor.execute(
            """
            INSERT INTO VetServices (VetID, ServiceName, PetCategory, Description, Price, DurationMinutes, IsActive)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            """,
            (user_id, service_name, pet_category, description, price, duration)
        )
    conn.commit()
    raw_cursor.close()
    cursor.close()
    conn.close()
    return redirect(url_for('vet_services_manager', user_id=user_id))

@app.route('/user/<int:user_id>/vet/<int:vet_id>/book', methods=['GET', 'POST'])
def book_vet_service(user_id, vet_id):
    ensure_vet_booking_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT UserID, Name, Role FROM Users WHERE UserID = %s", (user_id,))
    customer = cursor.fetchone()
    if not customer:
        cursor.close()
        conn.close()
        return "User not found", 404

    cursor.execute(
        """
        SELECT u.UserID, u.Name, v.ClinicName, v.Specialization, u.AccountStatus
        FROM Users u
        JOIN Vets v ON v.UserID = u.UserID
        WHERE u.UserID = %s AND u.Role = 'Vet'
        """,
        (vet_id,)
    )
    vet = cursor.fetchone()
    if not vet or vet.get('AccountStatus') != 'Active':
        cursor.close()
        conn.close()
        return "Vet not available", 404

    cursor.execute(
        """
        SELECT ServiceID, ServiceName, PetCategory, Description, Price, DurationMinutes
        FROM VetServices
        WHERE VetID = %s AND IsActive = 1
        ORDER BY ServiceID ASC
        LIMIT 1
        """,
        (vet_id,)
    )
    service = cursor.fetchone()
    if not service:
        cursor.close()
        conn.close()
        return "No active vet service available.", 400

    message = None
    message_type = "success"
    booking_summary = None
    next_available = preview_next_vet_slot(conn, vet_id, service['ServiceID'])

    if request.method == 'POST':
        note = (request.form.get('note') or '').strip()
        booking_summary, err = allocate_vet_slot(conn, vet_id, service['ServiceID'], user_id, None, note)
        if err:
            message = err
            message_type = "error"
        else:
            raw_cursor = conn.cursor()
            raw_cursor.execute(
                "INSERT INTO Notifications (UserID, Message) VALUES (%s, %s)",
                (
                    vet_id,
                    f"New appointment booked: #{booking_summary['appointment_id']} on {booking_summary['appointment_date']} (Serial {booking_summary['serial_no']})."
                )
            )
            raw_cursor.execute(
                "INSERT INTO Notifications (UserID, Message) VALUES (%s, %s)",
                (
                    user_id,
                    f"Appointment confirmed with Dr. {vet['Name']} on {booking_summary['appointment_date']} at {booking_summary['slot_start']} (Serial {booking_summary['serial_no']})."
                )
            )
            conn.commit()
            raw_cursor.close()
            message = "Appointment booked successfully."
            message_type = "success"
            next_available = preview_next_vet_slot(conn, vet_id, service['ServiceID'])

    cursor.close()
    conn.close()
    return render_template(
        'vet_booking_portal.html',
        user_id=user_id,
        customer=customer,
        vet=vet,
        service=service,
        next_available=next_available,
        message=message,
        message_type=message_type,
        booking_summary=booking_summary
    )


@app.route('/user/<int:user_id>/provider/services')
def provider_services_manager(user_id):
    ensure_service_provider_business_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user.get('Role') != 'ServiceProvider':
        cursor.close()
        conn.close()
        return "Access Denied", 403

    cursor.execute(
        """
        SELECT ServiceID, ServiceName, PetCategory, Description, Price, DurationMinutes, IsActive, CreatedAt
        FROM ProviderServices
        WHERE ProviderID = %s
        ORDER BY ServiceID DESC
        """,
        (user_id,)
    )
    services = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('provider_services_manage.html', user=user, user_id=user_id, services=services)


@app.route('/user/<int:user_id>/provider/appointments')
def provider_appointments_manager(user_id):
    ensure_service_provider_business_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user.get('Role') != 'ServiceProvider':
        cursor.close()
        conn.close()
        return "Access Denied", 403

    cursor.execute(
        """
        SELECT pa.AppointmentID, pa.AppointmentDate, pa.SerialNo, pa.SlotStart, pa.SlotEnd, pa.Status, pa.CustomerNote,
               c.Name AS CustomerName, c.Phone AS CustomerPhone, ps.ServiceName
        FROM ProviderAppointments pa
        JOIN Users c ON c.UserID = pa.CustomerID
        JOIN ProviderServices ps ON ps.ServiceID = pa.ServiceID
        WHERE pa.ProviderID = %s
        ORDER BY pa.AppointmentDate DESC, pa.SerialNo ASC
        """,
        (user_id,)
    )
    appointments = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('provider_appointments_manage.html', user=user, user_id=user_id, appointments=appointments)


@app.route('/user/<int:user_id>/provider/appointments/<int:appointment_id>/complete', methods=['POST'])
def provider_appointment_complete(user_id, appointment_id):
    ensure_service_provider_business_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user.get('Role') != 'ServiceProvider':
        cursor.close()
        conn.close()
        return "Access Denied", 403

    cursor.execute(
        """
        UPDATE ProviderAppointments
        SET Status = 'Completed'
        WHERE AppointmentID = %s AND ProviderID = %s AND Status NOT IN ('Completed', 'Cancelled')
        """,
        (appointment_id, user_id),
    )
    conn.commit()
    updated = cursor.rowcount
    cursor.close()
    conn.close()
    if not updated:
        return "Appointment not found or cannot be completed", 404
    return redirect(url_for('provider_appointments_manager', user_id=user_id))


@app.route('/user/<int:user_id>/provider/services/add', methods=['POST'])
def provider_services_add(user_id):
    ensure_service_provider_business_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user.get('Role') != 'ServiceProvider':
        cursor.close()
        conn.close()
        return "Access Denied", 403

    service_name = (request.form.get('service_name') or '').strip()
    pet_category = (request.form.get('pet_category') or '').strip() or None
    description = (request.form.get('description') or '').strip()
    price_raw = (request.form.get('price') or '').strip()
    duration_raw = (request.form.get('duration_minutes') or '').strip()

    try:
        price = round(float(price_raw), 2)
        duration = int(duration_raw)
    except (TypeError, ValueError):
        cursor.close()
        conn.close()
        return "Invalid fee or duration value.", 400

    if not service_name or not description or price < 0 or duration <= 0:
        cursor.close()
        conn.close()
        return "Invalid service input.", 400

    raw_cursor = conn.cursor()
    raw_cursor.execute("SELECT ServiceID FROM ProviderServices WHERE ProviderID = %s ORDER BY ServiceID ASC LIMIT 1", (user_id,))
    existing = raw_cursor.fetchone()
    if existing:
        raw_cursor.execute(
            """
            UPDATE ProviderServices
            SET ServiceName = %s, PetCategory = %s, Description = %s, Price = %s, DurationMinutes = %s, IsActive = 1
            WHERE ServiceID = %s AND ProviderID = %s
            """,
            (service_name, pet_category, description, price, duration, existing[0], user_id)
        )
    else:
        raw_cursor.execute(
            """
            INSERT INTO ProviderServices (ProviderID, ServiceName, PetCategory, Description, Price, DurationMinutes, IsActive)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            """,
            (user_id, service_name, pet_category, description, price, duration)
        )
    conn.commit()
    raw_cursor.close()
    cursor.close()
    conn.close()
    return redirect(url_for('provider_services_manager', user_id=user_id))


@app.route('/user/<int:user_id>/service-provider/<int:provider_id>/book', methods=['GET', 'POST'])
def book_provider_service(user_id, provider_id):
    ensure_service_provider_business_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT UserID, Name, Role FROM Users WHERE UserID = %s", (user_id,))
    customer = cursor.fetchone()
    if not customer:
        cursor.close()
        conn.close()
        return "User not found", 404

    cursor.execute(
        """
        SELECT u.UserID, u.Name, u.AccountStatus, p.BusinessName, p.ServiceType, p.AnimalExpertise
        FROM Users u
        JOIN ServiceProviderProfiles p ON p.UserID = u.UserID
        WHERE u.UserID = %s AND u.Role = 'ServiceProvider'
        """,
        (provider_id,)
    )
    prov = cursor.fetchone()
    if not prov or prov.get('AccountStatus') != 'Active':
        cursor.close()
        conn.close()
        return "Service provider not available", 404

    cursor.execute(
        """
        SELECT ServiceID, ServiceName, PetCategory, Description, Price, DurationMinutes
        FROM ProviderServices
        WHERE ProviderID = %s AND IsActive = 1
        ORDER BY ServiceID ASC
        LIMIT 1
        """,
        (provider_id,)
    )
    service = cursor.fetchone()
    if not service:
        cursor.close()
        conn.close()
        return "No active provider service available.", 400

    message = None
    message_type = "success"
    booking_summary = None
    next_available = preview_next_provider_slot(conn, provider_id, service['ServiceID'])

    if request.method == 'POST':
        note = (request.form.get('note') or '').strip()
        booking_summary, err = allocate_provider_slot(conn, provider_id, service['ServiceID'], user_id, None, note)
        if err:
            message = err
            message_type = "error"
        else:
            raw_cursor = conn.cursor()
            raw_cursor.execute(
                "INSERT INTO Notifications (UserID, Message) VALUES (%s, %s)",
                (
                    provider_id,
                    f"New booking: #{booking_summary['appointment_id']} on {booking_summary['appointment_date']} (Serial {booking_summary['serial_no']})."
                )
            )
            raw_cursor.execute(
                "INSERT INTO Notifications (UserID, Message) VALUES (%s, %s)",
                (
                    user_id,
                    f"Booking confirmed with {prov['BusinessName'] or prov['Name']} on {booking_summary['appointment_date']} at {booking_summary['slot_start']} (Serial {booking_summary['serial_no']})."
                )
            )
            conn.commit()
            raw_cursor.close()
            message = "Booking confirmed."
            message_type = "success"
            next_available = preview_next_provider_slot(conn, provider_id, service['ServiceID'])

    cursor.close()
    conn.close()
    return render_template(
        'provider_booking_portal.html',
        user_id=user_id,
        customer=customer,
        provider=prov,
        service=service,
        next_available=next_available,
        message=message,
        message_type=message_type,
        booking_summary=booking_summary
    )

@app.route('/user/<int:user_id>/product/<int:product_id>')
def product_detail(user_id, product_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get User
    cursor.execute("SELECT Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()

    # Get Product
    cursor.execute(
        """
        SELECT p.*, s.StoreName AS SellerName
        FROM Products p
        LEFT JOIN Sellers s ON p.SellerID = s.UserID
        WHERE p.ProductID = %s
        """,
        (product_id,)
    )
    product = cursor.fetchone()

    if not user:
        cursor.close()
        conn.close()
        return "User not found", 404

    if not product:
        cursor.close()
        conn.close()
        return "Product not found", 404

    cursor.execute(
        """
        SELECT p.ProductID, p.Name, p.PetCategory, p.Price, p.StockQuantity, p.ProductCategory,
               s.StoreName AS SellerName,
               COALESCE(SUM(oi.Quantity), 0) AS TotalSold
        FROM Products p
        LEFT JOIN Sellers s ON p.SellerID = s.UserID
        LEFT JOIN OrderItems oi ON p.ProductID = oi.ProductID
        LEFT JOIN Orders o ON oi.OrderID = o.OrderID AND o.OrderStatus = 'Delivered'
        WHERE p.Status = 'Active'
          AND p.ProductID <> %s
          AND (%s IS NULL OR p.PetCategory = %s)
        GROUP BY p.ProductID, p.Name, p.PetCategory, p.Price, p.StockQuantity, p.ProductCategory, s.StoreName
        ORDER BY TotalSold DESC, p.ProductID DESC
        LIMIT 8
        """,
        (product_id, product.get('PetCategory'), product.get('PetCategory'))
    )
    related_pets = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'product.html',
        username=user['Name'],
        user_id=user_id,
        role=user['Role'],
        product=product,
        related_pets=related_pets
    )

# ==========================================
# 2. CART & PRODUCT APIs
# ==========================================

@app.route('/api/featured-pets')
def featured_pets():
    # Same ranking for guests and signed-in users: trending (recent delivered sales), then best sellers.
    # `user_id` query param is accepted for compatibility but does not change ordering.
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT p.ProductID, p.Name, p.PetCategory, p.Price, p.StockQuantity, p.Status, p.ProductCategory,
               s.StoreName AS SellerName,
               COALESCE(SUM(CASE WHEN o.OrderStatus = 'Delivered' THEN oi.Quantity ELSE 0 END), 0) AS TotalSold,
               COALESCE(SUM(
                   CASE
                       WHEN o.OrderStatus = 'Delivered'
                            AND o.OrderDate >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 30 DAY)
                       THEN oi.Quantity
                       ELSE 0
                   END
               ), 0) AS RecentSold
        FROM Products p
        LEFT JOIN Sellers s ON p.SellerID = s.UserID
        LEFT JOIN OrderItems oi ON p.ProductID = oi.ProductID
        LEFT JOIN Orders o ON oi.OrderID = o.OrderID
        WHERE p.Status = 'Active'
        GROUP BY p.ProductID, p.Name, p.PetCategory, p.Price, p.StockQuantity, p.Status, p.ProductCategory, s.StoreName
        ORDER BY RecentSold DESC, TotalSold DESC, p.ProductID DESC
        LIMIT 8
        """
    )
    pets = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(pets)

@app.route('/api/browse-products')
def browse_products():
    q = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or '').strip()  # legacy single category
    categories_raw = (request.args.get('categories') or '').strip()  # comma-separated multi

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    sql = """
        SELECT p.*, s.StoreName AS SellerName
        FROM Products p
        LEFT JOIN Sellers s ON p.SellerID = s.UserID
        WHERE p.Status = 'Active'
    """
    params = []
    if q:
        sql += " AND Name LIKE %s"
        params.append(f"%{q}%")
    categories = [c.strip() for c in categories_raw.split(',') if c.strip()] if categories_raw else []
    if categories:
        placeholders = ','.join(['%s'] * len(categories))
        sql += f" AND PetCategory IN ({placeholders})"
        params.extend(categories)
    elif category:
        sql += " AND PetCategory = %s"
        params.append(category)
    sql += " ORDER BY p.ProductID DESC"

    cursor.execute(sql, tuple(params))
    products = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(products)

@app.route('/api/search')
def search_products():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT ProductID, Name, PetCategory
        FROM Products
        WHERE Status = 'Active' AND Name LIKE %s
        ORDER BY Name ASC
        LIMIT 20
        """,
        (f"%{q}%",)
    )
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(results)

@app.route('/api/cart/add', methods=['POST'])
def add_to_cart():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    product_id = data.get('product_id')

    if not user_id or not product_id:
        return jsonify({"error": "user_id and product_id are required"}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Check if cart exists
    cursor.execute("SELECT CartID FROM Carts WHERE CustomerID = %s", (user_id,))
    cart = cursor.fetchone()
    
    if not cart:
        cursor.execute("INSERT INTO Carts (CustomerID) VALUES (%s)", (user_id,))
        cart_id = cursor.lastrowid
    else:
        cart_id = cart['CartID']
        
    quantity = int(data.get('quantity', 1))
    if quantity < 1:
        return jsonify({"error": "quantity must be at least 1"}), 400

    # Add item or increase existing quantity
    cursor.execute(
        "SELECT CartItemID, Quantity FROM CartItems WHERE CartID = %s AND ProductID = %s",
        (cart_id, product_id)
    )
    existing_item = cursor.fetchone()
    if existing_item:
        cursor.execute(
            "UPDATE CartItems SET Quantity = Quantity + %s WHERE CartItemID = %s",
            (quantity, existing_item['CartItemID'])
        )
    else:
        cursor.execute(
            "INSERT INTO CartItems (CartID, ProductID, Quantity) VALUES (%s, %s, %s)",
            (cart_id, product_id, quantity)
        )
    
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Added to cart!"})

@app.route('/api/cart/<int:user_id>')
def get_cart(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.ProductID, p.Name, p.Price, ci.Quantity
        FROM CartItems ci
        JOIN Carts c ON ci.CartID = c.CartID
        JOIN Products p ON ci.ProductID = p.ProductID
        WHERE c.CustomerID = %s
    """, (user_id,))
    items = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(items)

@app.route('/api/cart/update', methods=['POST'])
def update_cart_item():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    product_id = data.get('product_id')
    action = data.get('action')
    if not user_id or not product_id or action not in ('increase', 'decrease'):
        return jsonify({"error": "user_id, product_id and valid action are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT CartID FROM Carts WHERE CustomerID = %s", (user_id,))
    cart = cursor.fetchone()
    if not cart:
        cursor.close()
        conn.close()
        return jsonify({"error": "Cart not found"}), 404

    cursor.execute(
        "SELECT CartItemID, Quantity FROM CartItems WHERE CartID = %s AND ProductID = %s",
        (cart['CartID'], product_id)
    )
    item = cursor.fetchone()
    if not item:
        cursor.close()
        conn.close()
        return jsonify({"error": "Item not found"}), 404

    if action == 'increase':
        cursor.execute("UPDATE CartItems SET Quantity = Quantity + 1 WHERE CartItemID = %s", (item['CartItemID'],))
    else:
        if item['Quantity'] <= 1:
            cursor.execute("DELETE FROM CartItems WHERE CartItemID = %s", (item['CartItemID'],))
        else:
            cursor.execute("UPDATE CartItems SET Quantity = Quantity - 1 WHERE CartItemID = %s", (item['CartItemID'],))

    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Cart updated"})

@app.route('/api/cart/validate-offer', methods=['POST'])
def validate_offer():
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip().upper()
    user_id = data.get('user_id')
    if not code or not user_id:
        return jsonify({"error": "code and user_id are required"}), 400

    ensure_discount_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT OfferID, DiscountPercent, AppliesToCategory, MaxUsesPerUser, MaxTotalUses
        FROM Offers
        WHERE OfferCode = %s
          AND ValidFrom <= NOW()
          AND ValidUntil >= NOW()
          AND (TargetUserID IS NULL OR TargetUserID = %s)
        LIMIT 1
        """,
        (code, user_id)
    )
    offer = cursor.fetchone()
    if not offer:
        cursor.close()
        conn.close()
        return jsonify({"error": "Invalid or expired code"}), 400

    # Enforce usage limits (one-time / limited)
    cursor.execute("SELECT COUNT(*) AS Cnt FROM OfferRedemptions WHERE OfferID = %s", (offer['OfferID'],))
    total_used = cursor.fetchone()['Cnt']
    if offer.get('MaxTotalUses') is not None and total_used >= int(offer['MaxTotalUses']):
        cursor.close()
        conn.close()
        return jsonify({"error": "This code has reached its maximum total uses."}), 400

    cursor.execute(
        "SELECT COUNT(*) AS Cnt FROM OfferRedemptions WHERE OfferID = %s AND UserID = %s",
        (offer['OfferID'], user_id)
    )
    used_by_user = cursor.fetchone()['Cnt']
    if offer.get('MaxUsesPerUser') is not None and used_by_user >= int(offer['MaxUsesPerUser']):
        cursor.close()
        conn.close()
        return jsonify({"error": "You have already used this code."}), 400

    # Category-limited: ensure cart has at least one item matching category
    if offer.get('AppliesToCategory'):
        cursor.execute(
            """
            SELECT COUNT(*) AS Cnt
            FROM CartItems ci
            JOIN Carts c ON ci.CartID = c.CartID
            JOIN Products p ON ci.ProductID = p.ProductID
            WHERE c.CustomerID = %s AND p.PetCategory = %s
            """,
            (user_id, offer['AppliesToCategory'])
        )
        cnt = cursor.fetchone()['Cnt']
        if int(cnt) == 0:
            cursor.close()
            conn.close()
            return jsonify({"error": f"This code only applies to {offer['AppliesToCategory']} category items."}), 400

    cursor.close()
    conn.close()
    return jsonify({
        "message": "Offer applied successfully",
        "discount": offer['DiscountPercent'],
        "applies_to_category": offer.get('AppliesToCategory')
    })

@app.route('/api/notifications/<int:user_id>')
def get_notifications(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT NotificationID, Message, IsRead, CreatedAt FROM Notifications WHERE UserID = %s ORDER BY CreatedAt DESC LIMIT 20",
        (user_id,)
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(rows)

# ==========================================
# 3. AUTH, PROFILE, CHECKOUT
# ==========================================

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT UserID, Name, Role, AccountStatus FROM Users WHERE Email = %s AND Password = %s",
        (email, password)
    )
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if not user:
        return jsonify({"error": "Invalid email or password."}), 401
    if user.get('AccountStatus') == 'Pending' and user.get('Role') in ('Seller', 'Vet', 'ServiceProvider'):
        return jsonify({"message": "Your account is pending approval.", "user": user, "pending": True}), 200
    return jsonify({"message": f"Welcome back, {user['Name']}!", "user": user}), 200

@app.route('/signup')
def signup_choice():
    return render_template('signup_choice.html')

def create_user(name, email, phone, password, role='Customer', status='Active'):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Users (Name, Email, Phone, Password, Role, AccountStatus) VALUES (%s, %s, %s, %s, %s, %s)",
        (name, email, phone, password, role, status)
    )
    user_id = cursor.lastrowid
    return conn, cursor, user_id

@app.route('/signup/customer', methods=['GET', 'POST'])
def signup_customer():
    if request.method == 'GET':
        return render_template('signup_customer.html')
    try:
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        conn, cursor, user_id = create_user(name, email, phone, password, 'Customer', 'Active')
        cursor.execute("INSERT INTO Customers (UserID) VALUES (%s)", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('login_page'))
    except mysql.connector.Error as err:
        return render_template('signup_customer.html', error=str(err))

@app.route('/signup/seller', methods=['GET', 'POST'])
def signup_seller():
    if request.method == 'GET':
        return render_template('signup_seller.html')
    try:
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        business_name = request.form.get('business_name')
        gov_id = request.form.get('gov_id')
        pickup_address = request.form.get('pickup_address')

        conn, cursor, user_id = create_user(name, email, phone, password, 'Seller', 'Pending')
        cursor.execute(
            "INSERT INTO Sellers (UserID, StoreName, BusinessName, GovernmentID, PickupAddress) VALUES (%s, %s, %s, %s, %s)",
            (user_id, business_name, business_name, gov_id, pickup_address)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('pending_approval'))
    except mysql.connector.Error as err:
        return render_template('signup_seller.html', error=str(err))

@app.route('/signup/vet', methods=['GET', 'POST'])
def signup_vet():
    if request.method == 'GET':
        return render_template('signup_vet.html')
    try:
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        clinic_name = request.form.get('clinic_name')
        specialization = request.form.get('specialization')
        experience = request.form.get('experience')
        consultation_fee = request.form.get('consultation_fee')
        gov_id = request.form.get('gov_id')
        education = request.form.get('education')

        conn, cursor, user_id = create_user(name, email, phone, password, 'Vet', 'Pending')
        cursor.execute(
            """
            INSERT INTO Vets (UserID, ClinicName, Specialization, ExperienceYears, ConsultationFee, GovernmentID, EducationInfo)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (user_id, clinic_name, specialization, experience, consultation_fee, gov_id, education)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('pending_approval'))
    except mysql.connector.Error as err:
        return render_template('signup_vet.html', error=str(err))

@app.route('/signup/service_provider', methods=['GET', 'POST'])
def signup_service_provider():
    if request.method == 'GET':
        return render_template('signup_service_provider.html')
    try:
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        business_name = request.form.get('business_name')
        service_type = (request.form.get('service_type') or '').strip() or 'General services'
        animal_expertise = (request.form.get('animal_expertise') or '').strip() or None
        location = (request.form.get('location') or '').strip() or None

        conn, cursor, user_id = create_user(name, email, phone, password, 'ServiceProvider', 'Pending')
        ensure_service_provider_business_schema()
        cursor.execute(
            """
            INSERT INTO ServiceProviderProfiles (UserID, BusinessName, ServiceType, Location, Description, AnimalExpertise)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                business_name,
                service_type,
                location,
                f"Service provider: {service_type}.",
                animal_expertise,
            ),
        )
        cursor.execute(
            "INSERT INTO Notifications (UserID, Message) VALUES (%s, %s)",
            (user_id, f"Service provider profile submitted: {business_name}")
        )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('pending_approval'))
    except mysql.connector.Error as err:
        return render_template('signup_service_provider.html', error=str(err))

@app.route('/pending-approval')
def pending_approval():
    return render_template('pending_approval.html')

@app.route('/user/<int:user_id>/profile')
def profile(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Name, Email, Phone, Role, Password FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if not user:
        return "User not found", 404
    return render_template('profile.html', user=user)

@app.route('/user/<int:user_id>/profile', methods=['POST'])
def update_profile(user_id):
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    confirm_password = request.form.get('confirm_password')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Name, Email, Phone, Role, Password FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.close()
        conn.close()
        return "User not found", 404
    if confirm_password != user['Password']:
        cursor.close()
        conn.close()
        return render_template('profile.html', user=user, message="Current password is incorrect.", message_type='error')

    cursor = conn.cursor()
    cursor.execute("UPDATE Users SET Name = %s, Email = %s, Phone = %s WHERE UserID = %s", (name, email, phone, user_id))
    conn.commit()
    cursor.close()
    conn.close()
    updated_user = dict(user)
    updated_user['Name'] = name
    updated_user['Email'] = email
    updated_user['Phone'] = phone
    return render_template('profile.html', user=updated_user, message="Profile updated successfully.", message_type='success')

@app.route('/user/<int:user_id>/history')
def history(user_id):
    return "Order history page is under construction."

@app.route('/user/<int:user_id>/discounts')
def my_discounts(user_id):
    ensure_discount_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.close()
        conn.close()
        return "User not found", 404

    cursor.execute(
        """
        SELECT o.OfferID, o.OfferCode, o.DiscountPercent, o.ValidUntil, o.AppliesToCategory, o.MaxUsesPerUser, o.MaxTotalUses,
               (SELECT COUNT(*) FROM OfferRedemptions r WHERE r.OfferID = o.OfferID AND r.UserID = %s) AS UsedByUser,
               (SELECT COUNT(*) FROM OfferRedemptions r2 WHERE r2.OfferID = o.OfferID) AS TotalUsed
        FROM Offers o
        WHERE o.ValidFrom <= NOW()
          AND o.ValidUntil >= NOW()
          AND (o.TargetUserID IS NULL OR o.TargetUserID = %s)
        ORDER BY o.DiscountPercent DESC, o.ValidUntil ASC
        """,
        (user_id, user_id)
    )
    discounts = cursor.fetchall()
    cursor.close()
    conn.close()

    for d in discounts:
        max_user = d.get('MaxUsesPerUser')
        max_total = d.get('MaxTotalUses')
        used_user = int(d.get('UsedByUser') or 0)
        used_total = int(d.get('TotalUsed') or 0)
        d['RemainingUserUses'] = None if max_user is None else max(0, int(max_user) - used_user)
        d['RemainingTotalUses'] = None if max_total is None else max(0, int(max_total) - used_total)

    return render_template('my_discounts.html', user=user, discounts=discounts)

@app.route('/user/<int:user_id>/checkout')
def checkout(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT UserID, Name, Phone FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.close()
        conn.close()
        return "User not found", 404
    cursor.execute(
        """
        SELECT p.ProductID, p.Name, p.Price, ci.Quantity
        FROM CartItems ci
        JOIN Carts c ON ci.CartID = c.CartID
        JOIN Products p ON ci.ProductID = p.ProductID
        WHERE c.CustomerID = %s
        """,
        (user_id,)
    )
    cart_items = cursor.fetchall()
    cursor.close()
    conn.close()
    subtotal = sum(float(item['Price']) * int(item['Quantity']) for item in cart_items)
    delivery_fee = 5.00 if cart_items else 0.00
    return render_template(
        'checkout.html',
        user_id=user_id,
        user=user,
        cart_items=cart_items,
        subtotal=subtotal,
        delivery_fee=delivery_fee
    )

@app.route('/api/checkout/process', methods=['POST'])
def process_checkout():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    address = data.get('address')
    discount_percent = float(data.get('discount_percent', 0))
    discount_code = (data.get('code') or '').strip().upper()
    if not user_id or not address:
        return jsonify({"error": "user_id and address are required"}), 400

    ensure_discount_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT CartID FROM Carts WHERE CustomerID = %s", (user_id,))
    cart = cursor.fetchone()
    if not cart:
        cursor.close()
        conn.close()
        return jsonify({"error": "Cart not found"}), 404

    cursor.execute(
        """
        SELECT ci.CartItemID, ci.ProductID, ci.Quantity, p.Price, p.StockQuantity, p.PetCategory
        FROM CartItems ci
        JOIN Products p ON ci.ProductID = p.ProductID
        WHERE ci.CartID = %s
        """,
        (cart['CartID'],)
    )
    items = cursor.fetchall()
    if not items:
        cursor.close()
        conn.close()
        return jsonify({"error": "Cart is empty"}), 400

    subtotal = sum(float(item['Price']) * int(item['Quantity']) for item in items)

    offer = None
    discount_amount = subtotal * (discount_percent / 100.0)
    if discount_code:
        cursor.execute(
            """
            SELECT OfferID, DiscountPercent, AppliesToCategory, MaxUsesPerUser, MaxTotalUses
            FROM Offers
            WHERE OfferCode = %s
              AND ValidFrom <= NOW()
              AND ValidUntil >= NOW()
              AND (TargetUserID IS NULL OR TargetUserID = %s)
            LIMIT 1
            """,
            (discount_code, user_id)
        )
        offer = cursor.fetchone()
        if not offer:
            cursor.close()
            conn.close()
            return jsonify({"error": "Invalid or expired discount code."}), 400

        cursor.execute("SELECT COUNT(*) AS Cnt FROM OfferRedemptions WHERE OfferID = %s", (offer['OfferID'],))
        total_used = cursor.fetchone()['Cnt']
        if offer.get('MaxTotalUses') is not None and total_used >= int(offer['MaxTotalUses']):
            cursor.close()
            conn.close()
            return jsonify({"error": "This code has reached its maximum total uses."}), 400

        cursor.execute(
            "SELECT COUNT(*) AS Cnt FROM OfferRedemptions WHERE OfferID = %s AND UserID = %s",
            (offer['OfferID'], user_id)
        )
        used_by_user = cursor.fetchone()['Cnt']
        if offer.get('MaxUsesPerUser') is not None and used_by_user >= int(offer['MaxUsesPerUser']):
            cursor.close()
            conn.close()
            return jsonify({"error": "You have already used this code."}), 400

        percent = float(offer['DiscountPercent'])
        if offer.get('AppliesToCategory'):
            eligible = sum(
                float(it['Price']) * int(it['Quantity'])
                for it in items
                if it.get('PetCategory') == offer['AppliesToCategory']
            )
            if eligible <= 0:
                cursor.close()
                conn.close()
                return jsonify({"error": f"This code only applies to {offer['AppliesToCategory']} category items."}), 400
            discount_amount = eligible * (percent / 100.0)
        else:
            discount_amount = subtotal * (percent / 100.0)

    delivery_fee = 5.00
    total = max(0.0, subtotal - discount_amount) + delivery_fee

    raw_cursor = conn.cursor()
    raw_cursor.execute(
        "INSERT INTO Orders (CustomerID, ShippingAddress, TotalAmount, OrderStatus) VALUES (%s, %s, %s, 'Pending')",
        (user_id, address, total)
    )
    order_id = raw_cursor.lastrowid
    for item in items:
        raw_cursor.execute(
            "SELECT Name, SellerID, StockQuantity FROM Products WHERE ProductID = %s",
            (item['ProductID'],)
        )
        product_meta = raw_cursor.fetchone()
        seller_id = product_meta[1] if product_meta and len(product_meta) > 1 else None
        product_name = product_meta[0] if product_meta else f"Product #{item['ProductID']}"
        current_stock = int(product_meta[2] or 0) if product_meta and len(product_meta) > 2 else 0

        raw_cursor.execute(
            "INSERT INTO OrderItems (OrderID, ProductID, Quantity, PriceAtPurchase) VALUES (%s, %s, %s, %s)",
            (order_id, item['ProductID'], item['Quantity'], item['Price'])
        )
        raw_cursor.execute(
            "UPDATE Products SET StockQuantity = GREATEST(0, StockQuantity - %s) WHERE ProductID = %s",
            (item['Quantity'], item['ProductID'])
        )

        # Notify seller about new order line and stock-out events.
        if seller_id:
            ordered_qty = int(item['Quantity'])
            new_stock = max(0, current_stock - ordered_qty)
            raw_cursor.execute(
                "INSERT INTO Notifications (UserID, Message) VALUES (%s, %s)",
                (
                    seller_id,
                    f"New order #{order_id}: {ordered_qty} unit(s) of '{product_name}' were purchased."
                )
            )
            if new_stock <= 0:
                raw_cursor.execute(
                    "INSERT INTO Notifications (UserID, Message) VALUES (%s, %s)",
                    (
                        seller_id,
                        f"Stock out alert: '{product_name}' is now out of stock after order #{order_id}. Please restock."
                    )
                )
    raw_cursor.execute("DELETE FROM CartItems WHERE CartID = %s", (cart['CartID'],))
    if offer:
        raw_cursor.execute(
            "INSERT INTO OfferRedemptions (OfferID, UserID, OrderID) VALUES (%s, %s, %s)",
            (offer['OfferID'], user_id, order_id)
        )
    conn.commit()
    raw_cursor.close()
    cursor.close()
    conn.close()
    return jsonify({"message": "Order placed successfully", "order_id": order_id})

if __name__ == '__main__':
    app.run(debug=True)