from flask import Blueprint, render_template, jsonify, redirect, url_for, request
import mysql.connector

admin_bp = Blueprint('admin', __name__)

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '2763', 
    'database': 'petnest_db'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

def ensure_discount_schema():
    """
    Ensures Offers table has discount-limiting columns and that OfferRedemptions exists.
    This prevents admin dashboard crashes on fresh databases.
    """
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

    # Business rule requested: NEST20 can be used once per user (global)
    cursor.execute(
        "UPDATE Offers SET MaxUsesPerUser = 1, TargetUserID = NULL WHERE OfferCode = 'NEST20'"
    )

    conn.commit()
    cursor.close()
    conn.close()

# Helper function to check admin status and get the sidebar notification bubble
def get_admin_context(user_id, cursor):
    cursor.execute("SELECT Name, Role FROM Users WHERE UserID = %s", (user_id,))
    user = cursor.fetchone()
    if not user or user['Role'] != 'Admin':
        return None, None
    
    cursor.execute("SELECT COUNT(*) as count FROM Users WHERE AccountStatus = 'Pending'")
    pending_count = cursor.fetchone()['count']
    return user, pending_count

def table_exists(cursor, table_name):
    cursor.execute(
        """
        SELECT COUNT(*) AS Cnt
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        """,
        (db_config['database'], table_name)
    )
    return int(cursor.fetchone()['Cnt']) > 0

# --- 1. OVERVIEW (Default Dashboard) ---
@admin_bp.route('/admin/<int:user_id>/dashboard')
def admin_dashboard(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    user, pending_count = get_admin_context(user_id, cursor)
    if not user: return "Access Denied", 403

    cursor.execute(
        """
        SELECT COALESCE(SUM(TotalAmount), 0) as TodayRev
        FROM Orders
        WHERE DATE(OrderDate) = CURDATE() AND OrderStatus = 'Delivered'
        """
    )
    today_rev = cursor.fetchone()['TodayRev']

    cursor.execute(
        """
        SELECT COUNT(*) as WeeklyCount
        FROM Orders
        WHERE OrderDate >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) AND OrderStatus = 'Delivered'
        """
    )
    weekly_orders = cursor.fetchone()['WeeklyCount']

    cursor.execute("SELECT COUNT(*) as CustomerCount FROM Users WHERE Role = 'Customer'")
    active_customers = cursor.fetchone()['CustomerCount']

    cursor.execute(
        """
        SELECT COUNT(*) as CompletedCount
        FROM Orders
        WHERE OrderStatus = 'Delivered'
        """
    )
    completed_orders = cursor.fetchone()['CompletedCount']

    cursor.execute(
        """
        SELECT COALESCE(AVG(TotalAmount), 0) as AvgOrderValue
        FROM Orders
        WHERE OrderStatus = 'Delivered'
        """
    )
    avg_order_value = cursor.fetchone()['AvgOrderValue']

    cursor.execute("""
        SELECT p.Name, p.PetCategory, p.Price, SUM(oi.Quantity) as TotalSold
        FROM OrderItems oi
        JOIN Orders o ON oi.OrderID = o.OrderID
        JOIN Products p ON oi.ProductID = p.ProductID
        WHERE o.OrderStatus = 'Delivered'
        GROUP BY p.ProductID ORDER BY TotalSold DESC LIMIT 3
    """)
    top_products = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('admin_dashboard.html', active_tab='overview', username=user['Name'], user_id=user_id, 
                           pending_approvals=pending_count, today_rev=today_rev, weekly_orders=weekly_orders, 
                           active_customers=active_customers, top_products=top_products,
                           completed_orders=completed_orders, avg_order_value=avg_order_value)

# --- 2. USERS & SELLERS ---
@admin_bp.route('/admin/<int:user_id>/users')
def admin_users(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    user, pending_count = get_admin_context(user_id, cursor)
    if not user: return "Access Denied", 403

    cursor.execute("SELECT UserID, Name, Email, Role, AccountStatus FROM Users ORDER BY UserID DESC")
    all_users = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('admin_dashboard.html', active_tab='users', username=user['Name'], user_id=user_id, 
                           pending_approvals=pending_count, all_users=all_users)

# --- 3. APPROVALS ---
@admin_bp.route('/admin/<int:user_id>/approvals')
def admin_approvals(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    user, pending_count = get_admin_context(user_id, cursor)
    if not user: return "Access Denied", 403

    cursor.execute("SELECT UserID, Name, Email, Role FROM Users WHERE AccountStatus = 'Pending'")
    pending_users = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('admin_dashboard.html', active_tab='approvals', username=user['Name'], user_id=user_id, 
                           pending_approvals=pending_count, pending_users=pending_users)

# --- PLACEHOLDERS FOR FUTURE TABS ---
@admin_bp.route('/admin/<int:user_id>/products')
def admin_products(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    user, pending_count = get_admin_context(user_id, cursor)
    if not user:
        cursor.close()
        conn.close()
        return "Access Denied", 403
    cursor.execute("""
        SELECT p.ProductID, p.Name, p.PetCategory, p.Price, p.StockQuantity, p.Status,
               s.StoreName as SellerName
        FROM Products p
        LEFT JOIN Sellers s ON p.SellerID = s.UserID
        ORDER BY p.ProductID DESC
    """)
    products = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template(
        'admin_dashboard.html',
        active_tab='products',
        username=user['Name'],
        user_id=user_id,
        pending_approvals=pending_count,
        products=products
    )

@admin_bp.route('/admin/<int:user_id>/orders')
def admin_orders(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    user, pending_count = get_admin_context(user_id, cursor)
    if not user:
        cursor.close()
        conn.close()
        return "Access Denied", 403
    cursor.execute(
        """
        SELECT o.OrderID, o.OrderDate, o.TotalAmount, o.OrderStatus, u.Name as CustomerName
        FROM Orders o
        JOIN Users u ON o.CustomerID = u.UserID
        ORDER BY o.OrderDate DESC
        """
    )
    orders = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template(
        'admin_dashboard.html',
        active_tab='orders',
        username=user['Name'],
        user_id=user_id,
        pending_approvals=pending_count,
        orders=orders
    )

@admin_bp.route('/admin/<int:user_id>/transactions')
def admin_transactions(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    user, pending_count = get_admin_context(user_id, cursor)
    if not user:
        cursor.close()
        conn.close()
        return "Access Denied", 403
    cursor.close()
    conn.close()
    return render_template('admin_dashboard.html', active_tab='transactions', username=user['Name'], user_id=user_id, pending_approvals=pending_count)

@admin_bp.route('/admin/<int:user_id>/services')
def admin_services(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    user, pending_count = get_admin_context(user_id, cursor)
    if not user:
        cursor.close()
        conn.close()
        return "Access Denied", 403

    vet_services = []
    provider_services = []

    if table_exists(cursor, 'VetServices'):
        cursor.execute(
            """
            SELECT vs.ServiceID, vs.ServiceName, vs.PetCategory, vs.Description, vs.Price, vs.DurationMinutes, vs.IsActive, vs.CreatedAt,
                   u.UserID AS VetID, u.Name AS VetName, v.ClinicName
            FROM VetServices vs
            JOIN Users u ON vs.VetID = u.UserID
            LEFT JOIN Vets v ON v.UserID = u.UserID
            ORDER BY vs.ServiceID DESC
            """
        )
        vet_services = cursor.fetchall()
    elif table_exists(cursor, 'vet_services'):
        cursor.execute(
            """
            SELECT s.service_id AS ServiceID, s.service_name AS ServiceName, s.category AS PetCategory, s.description AS Description,
                   s.price AS Price, s.duration_minutes AS DurationMinutes,
                   CASE WHEN s.status = 'Active' THEN 1 ELSE 0 END AS IsActive,
                   s.created_at AS CreatedAt,
                   u.UserID AS VetID, u.Name AS VetName, v.ClinicName
            FROM vet_services s
            JOIN Users u ON s.vet_id = u.UserID
            LEFT JOIN Vets v ON v.UserID = u.UserID
            ORDER BY s.service_id DESC
            """
        )
        vet_services = cursor.fetchall()

    if table_exists(cursor, 'ProviderServices'):
        cursor.execute(
            """
            SELECT ps.ServiceID, ps.ServiceName, ps.PetCategory AS ServiceCategory, ps.Description, ps.Price,
                   ps.DurationMinutes, ps.IsActive, ps.CreatedAt,
                   u.UserID AS ProviderID, u.Name AS ProviderName, u.AccountStatus AS ProviderAccountStatus,
                   spp.BusinessName, spp.ServiceType, spp.AnimalExpertise
            FROM ProviderServices ps
            JOIN Users u ON ps.ProviderID = u.UserID
            LEFT JOIN ServiceProviderProfiles spp ON spp.UserID = u.UserID
            ORDER BY ps.ServiceID DESC
            """
        )
        provider_services = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template(
        'admin_dashboard.html',
        active_tab='services',
        username=user['Name'],
        user_id=user_id,
        pending_approvals=pending_count,
        vet_services=vet_services,
        provider_services=provider_services
    )

@admin_bp.route('/admin/<int:user_id>/discounts')
def admin_discounts(user_id):
    ensure_discount_schema()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    user, pending_count = get_admin_context(user_id, cursor)
    if not user:
        cursor.close()
        conn.close()
        return "Access Denied", 403
    cursor.execute(
        """
        SELECT o.OfferID, o.OfferCode, o.DiscountPercent, o.ValidFrom, o.ValidUntil, o.TargetUserID,
               o.AppliesToCategory, o.MaxUsesPerUser, o.MaxTotalUses,
               CASE WHEN o.ValidUntil >= NOW() THEN 1 ELSE 0 END AS IsActive,
               u.Name as TargetUserName,
               (SELECT COUNT(*) FROM OfferRedemptions r WHERE r.OfferID = o.OfferID) AS TotalRedemptions
        FROM Offers o
        LEFT JOIN Users u ON o.TargetUserID = u.UserID
        ORDER BY o.OfferID DESC
        """
    )
    discounts = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template(
        'admin_dashboard.html',
        active_tab='discounts',
        username=user['Name'],
        user_id=user_id,
        pending_approvals=pending_count,
        discounts=discounts
    )

# --- API FOR CHARTS ---
@admin_bp.route('/api/admin/revenue-chart')
def revenue_chart():
    period = request.args.get('period', '7d')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if period == '24h':
        cursor.execute(
            """
            SELECT DATE_FORMAT(OrderDate, '%H:00') as Label, COALESCE(SUM(TotalAmount), 0) as Amount
            FROM Orders
            WHERE OrderDate >= DATE_SUB(NOW(), INTERVAL 24 HOUR) AND OrderStatus = 'Delivered'
            GROUP BY HOUR(OrderDate), Label
            ORDER BY HOUR(OrderDate) ASC
            """
        )
    elif period == '90d':
        cursor.execute(
            """
            SELECT DATE_FORMAT(OrderDate, '%Y-%u') as SortKey, CONCAT('W', DATE_FORMAT(OrderDate, '%u')) as Label, COALESCE(SUM(TotalAmount), 0) as Amount
            FROM Orders
            WHERE OrderDate >= DATE_SUB(CURDATE(), INTERVAL 90 DAY) AND OrderStatus = 'Delivered'
            GROUP BY SortKey, Label
            ORDER BY SortKey ASC
            """
        )
    elif period == '12m':
        cursor.execute(
            """
            SELECT DATE_FORMAT(OrderDate, '%Y-%m') as SortKey, DATE_FORMAT(OrderDate, '%b %Y') as Label, COALESCE(SUM(TotalAmount), 0) as Amount
            FROM Orders
            WHERE OrderDate >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) AND OrderStatus = 'Delivered'
            GROUP BY SortKey, Label
            ORDER BY SortKey ASC
            """
        )
    else:
        cursor.execute(
            """
            SELECT DATE_FORMAT(OrderDate, '%Y-%m-%d') as SortKey, DATE_FORMAT(OrderDate, '%a') as Label, COALESCE(SUM(TotalAmount), 0) as Amount
            FROM Orders
            WHERE OrderDate >= DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND OrderStatus = 'Delivered'
            GROUP BY SortKey, Label
            ORDER BY SortKey ASC
            """
        )

    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({'labels': [row['Label'] for row in data], 'data': [float(row['Amount']) for row in data]})

@admin_bp.route('/api/admin/overview-metrics')
def overview_metrics():
    period = request.args.get('period', '7d')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if period == '24h':
        time_filter = "OrderDate >= DATE_SUB(NOW(), INTERVAL 24 HOUR)"
    elif period == '90d':
        time_filter = "OrderDate >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)"
    elif period == '12m':
        time_filter = "OrderDate >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)"
    else:
        time_filter = "OrderDate >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)"

    cursor.execute(
        f"""
        SELECT
            COALESCE(SUM(TotalAmount), 0) as Revenue,
            COUNT(*) as OrdersCount,
            COALESCE(AVG(TotalAmount), 0) as AvgOrderValue
        FROM Orders
        WHERE {time_filter} AND OrderStatus = 'Delivered'
        """
    )
    order_metrics = cursor.fetchone()

    cursor.execute(
        f"""
        SELECT COUNT(DISTINCT CustomerID) as UniqueCustomers
        FROM Orders
        WHERE {time_filter} AND OrderStatus = 'Delivered'
        """
    )
    customer_metrics = cursor.fetchone()

    cursor.execute(
        f"""
        SELECT COALESCE(SUM(oi.Quantity), 0) as UnitsSold
        FROM OrderItems oi
        JOIN Orders o ON oi.OrderID = o.OrderID
        WHERE {time_filter} AND o.OrderStatus = 'Delivered'
        """
    )
    unit_metrics = cursor.fetchone()

    cursor.close()
    conn.close()

    return jsonify({
        'revenue': float(order_metrics['Revenue']),
        'orders_count': int(order_metrics['OrdersCount']),
        'avg_order_value': float(order_metrics['AvgOrderValue']),
        'unique_customers': int(customer_metrics['UniqueCustomers']),
        'units_sold': int(unit_metrics['UnitsSold'])
    })

# --- API FOR APPROVALS ---
@admin_bp.route('/api/admin/update-account-status', methods=['POST'])
def update_account_status():
    try:
        data = request.json
        target_user_id = data.get('target_user_id')
        new_status = data.get('status') # Will be 'Active' or 'Rejected'

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update the user's status in the database
        cursor.execute("UPDATE Users SET AccountStatus = %s WHERE UserID = %s", (new_status, target_user_id))
        conn.commit()
        
        cursor.close()
        conn.close()

        return jsonify({"message": f"Account successfully marked as {new_status}!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

# --- API FOR USER MANAGEMENT (Add to admin.py) ---
@admin_bp.route('/api/admin/edit-admin', methods=['POST'])
def edit_admin():
    try:
        data = request.json
        target_id = data.get('target_user_id')
        new_name = data.get('name')
        new_password = data.get('password')

        conn = get_db_connection()
        cursor = conn.cursor()
        
        if new_password: # If they typed a new password, update both
            cursor.execute("UPDATE Users SET Name = %s, Password = %s WHERE UserID = %s", (new_name, new_password, target_id))
        else: # Otherwise, just update the name
            cursor.execute("UPDATE Users SET Name = %s WHERE UserID = %s", (new_name, target_id))
            
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Admin details updated!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/restrict-user', methods=['POST'])
def restrict_user():
    try:
        data = request.json
        target_id = data.get('target_user_id')
        reason = data.get('reason')
        action = data.get('action') # 'Restrict' or 'Unrestrict'

        conn = get_db_connection()
        cursor = conn.cursor()
        
        if action == 'Restrict':
            cursor.execute("UPDATE Users SET AccountStatus = 'Restricted' WHERE UserID = %s", (target_id,))
            cursor.execute("INSERT INTO Notifications (UserID, Message) VALUES (%s, %s)", (target_id, reason))
            msg = "User restricted successfully."
        else:
            cursor.execute("UPDATE Users SET AccountStatus = 'Active' WHERE UserID = %s", (target_id,))
            cursor.execute("INSERT INTO Notifications (UserID, Message) VALUES (%s, %s)", (target_id, "Your account restriction has been lifted. You may resume normal activity."))
            msg = "User unrestricted successfully."
            
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": msg}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/send-notification', methods=['POST'])
def send_notification():
    try:
        data = request.json
        target_id = data.get('target_user_id')
        message = data.get('message')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO Notifications (UserID, Message) VALUES (%s, %s)", (target_id, message))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Notification sent!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/products/update', methods=['POST'])
def update_product():
    try:
        data = request.get_json(silent=True) or {}
        product_id = data.get('product_id')
        price = data.get('price')
        stock = data.get('stock')
        status = data.get('status')

        if not product_id:
            return jsonify({"error": "product_id is required"}), 400
        if price is None or stock is None or status not in ('Active', 'Inactive'):
            return jsonify({"error": "price, stock and valid status are required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE Products SET Price = %s, StockQuantity = %s, Status = %s WHERE ProductID = %s",
            (price, stock, status, product_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Product updated successfully."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/products/toggle-status', methods=['POST'])
def toggle_product_status():
    try:
        data = request.get_json(silent=True) or {}
        product_id = data.get('product_id')
        new_status = data.get('status')
        if not product_id or new_status not in ('Active', 'Inactive'):
            return jsonify({"error": "product_id and valid status are required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE Products SET Status = %s WHERE ProductID = %s", (new_status, product_id))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": f"Product marked as {new_status}."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/products/create', methods=['POST'])
def create_product():
    try:
        data = request.get_json(silent=True) or {}
        name = data.get('name')
        category = data.get('pet_category')
        price = data.get('price')
        stock = data.get('stock')
        status = data.get('status', 'Active')
        seller_id = data.get('seller_id')
        if not name or not category or price is None or stock is None:
            return jsonify({"error": "name, pet_category, price and stock are required"}), 400
        if status not in ('Active', 'Inactive'):
            return jsonify({"error": "Invalid status"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO Products (SellerID, Name, PetCategory, Price, StockQuantity, Status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (seller_id, name, category, price, stock, status)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Product created successfully."}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/orders/update-status', methods=['POST'])
def update_order_status():
    try:
        data = request.get_json(silent=True) or {}
        order_id = data.get('order_id')
        status = data.get('status')
        allowed = ('Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled')
        if not order_id or status not in allowed:
            return jsonify({"error": "order_id and valid status are required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE Orders SET OrderStatus = %s WHERE OrderID = %s", (status, order_id))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": f"Order status updated to {status}."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/discounts/create', methods=['POST'])
def create_discount():
    try:
        ensure_discount_schema()
        data = request.get_json(silent=True) or {}
        code = (data.get('code') or '').strip().upper()
        discount = data.get('discount_percent')
        target_user_id = data.get('target_user_id')
        valid_days_raw = data.get('valid_days')
        applies_to_category = (data.get('applies_to_category') or '').strip() or None
        one_time_use = bool(data.get('one_time_use'))
        max_total_uses = data.get('max_total_uses')
        if not code or discount is None:
            return jsonify({"error": "code and discount_percent are required"}), 400

        valid_days = None
        if valid_days_raw not in (None, ''):
            valid_days = int(valid_days_raw)
            if valid_days < 1:
                return jsonify({"error": "valid_days must be at least 1"}), 400

        max_total_uses_value = None
        if max_total_uses not in (None, ''):
            max_total_uses_value = int(max_total_uses)
            if max_total_uses_value < 1:
                return jsonify({"error": "max_total_uses must be at least 1"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        if valid_days is None:
            # Empty days means lifetime discount (far-future expiry).
            cursor.execute(
                """
                INSERT INTO Offers (OfferCode, DiscountPercent, ValidFrom, ValidUntil, TargetUserID, AppliesToCategory, MaxUsesPerUser, MaxTotalUses)
                VALUES (%s, %s, NOW(), '2099-12-31 23:59:59', %s, %s, %s, %s)
                """,
                (
                    code,
                    discount,
                    target_user_id or None,
                    applies_to_category,
                    1 if one_time_use else None,
                    max_total_uses_value
                )
            )
        else:
            cursor.execute(
                """
                INSERT INTO Offers (OfferCode, DiscountPercent, ValidFrom, ValidUntil, TargetUserID, AppliesToCategory, MaxUsesPerUser, MaxTotalUses)
                VALUES (%s, %s, NOW(), DATE_ADD(NOW(), INTERVAL %s DAY), %s, %s, %s, %s)
                """,
                (
                    code,
                    discount,
                    valid_days,
                    target_user_id or None,
                    applies_to_category,
                    1 if one_time_use else None,
                    max_total_uses_value
                )
            )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Discount created successfully."}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/discounts/toggle', methods=['POST'])
def toggle_discount():
    try:
        ensure_discount_schema()
        data = request.get_json(silent=True) or {}
        offer_id = data.get('offer_id')
        activate = bool(data.get('activate'))
        if not offer_id:
            return jsonify({"error": "offer_id is required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        if activate:
            cursor.execute(
                "UPDATE Offers SET ValidFrom = NOW(), ValidUntil = DATE_ADD(NOW(), INTERVAL 30 DAY) WHERE OfferID = %s",
                (offer_id,)
            )
            msg = "Discount activated."
        else:
            cursor.execute(
                "UPDATE Offers SET ValidUntil = DATE_SUB(NOW(), INTERVAL 1 SECOND) WHERE OfferID = %s",
                (offer_id,)
            )
            msg = "Discount deactivated."
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": msg}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500