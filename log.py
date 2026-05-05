from flask import Flask, render_template, request, jsonify
import mysql.connector

app = Flask(__name__)

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '2763',
    'database': 'petnest_db'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

@app.route('/signup')
def signup_page():
    return render_template('signup_choice.html')

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.json
        name, email, password = data.get('name'), data.get('email'), data.get('password')
        phone, role = data.get('phone'), data.get('role', 'Customer')

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("INSERT INTO Users (Name, Email, Password, Phone, Role) VALUES (%s, %s, %s, %s, %s)", 
                       (name, email, password, phone, role))
        new_user_id = cursor.lastrowid 

        if role == 'Customer':
            cursor.execute("INSERT INTO Customers (UserID) VALUES (%s)", (new_user_id,))
        elif role == 'Seller':
            cursor.execute("INSERT INTO Sellers (UserID, StoreName) VALUES (%s, %s)", (new_user_id, f"{name}'s Store"))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "Account created successfully!", "user_id": new_user_id}), 201
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 400

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        email, password = data.get('email'), data.get('password')

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT UserID, Name, Role FROM Users WHERE Email = %s AND Password = %s", (email, password))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            return jsonify({"message": f"Welcome back, {user['Name']}!", "user": user}), 200
        return jsonify({"error": "Invalid email or password."}), 401
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500

if __name__ == '__main__':
    app.run(port=5001, debug=True)