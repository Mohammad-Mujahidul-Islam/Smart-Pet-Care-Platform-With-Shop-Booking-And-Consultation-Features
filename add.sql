-- ============================================================
-- PetNest complete database reset + bootstrap
-- Run this file in MySQL to recreate everything from scratch.
-- ============================================================

DROP DATABASE IF EXISTS petnest_db;
CREATE DATABASE petnest_db;
USE petnest_db;

-- ============================================================
-- 1) USERS / ROLE PROFILES
-- ============================================================

CREATE TABLE Users (
    UserID INT AUTO_INCREMENT PRIMARY KEY,
    Name VARCHAR(100) NOT NULL,
    Email VARCHAR(100) NOT NULL UNIQUE,
    Password VARCHAR(255) NOT NULL,
    Phone VARCHAR(20),
    Role ENUM('Customer', 'Seller', 'Vet', 'ServiceProvider', 'Admin') NOT NULL DEFAULT 'Customer',
    AccountStatus ENUM('Pending', 'Active', 'Restricted', 'Rejected') NOT NULL DEFAULT 'Active'
);

CREATE TABLE Customers (
    UserID INT PRIMARY KEY,
    ShippingAddress TEXT,
    FOREIGN KEY (UserID) REFERENCES Users(UserID) ON DELETE CASCADE
);

CREATE TABLE Sellers (
    UserID INT PRIMARY KEY,
    StoreName VARCHAR(100),
    BusinessName VARCHAR(150),
    Description TEXT,
    GovernmentID VARCHAR(50),
    DOB DATE,
    PickupAddress TEXT,
    ReturnAddress TEXT,
    SocialLinks TEXT,
    AgreePolicies BOOLEAN DEFAULT FALSE,
    Rating DECIMAL(3,2) DEFAULT 0.00,
    TotalSales INT DEFAULT 0,
    FOREIGN KEY (UserID) REFERENCES Users(UserID) ON DELETE CASCADE
);

CREATE TABLE Vets (
    UserID INT PRIMARY KEY,
    ClinicName VARCHAR(100),
    Specialization VARCHAR(100),
    ExperienceYears INT DEFAULT 0,
    ConsultationFee DECIMAL(10,2) DEFAULT 0.00,
    GovernmentID VARCHAR(50),
    EducationInfo TEXT,
    CertDocPath VARCHAR(255),
    FOREIGN KEY (UserID) REFERENCES Users(UserID) ON DELETE CASCADE
);

CREATE TABLE ServiceProviderProfiles (
    UserID INT PRIMARY KEY,
    BusinessName VARCHAR(150),
    ServiceType VARCHAR(100),
    Location VARCHAR(255),
    Description TEXT,
    AnimalExpertise VARCHAR(100) NULL,
    FOREIGN KEY (UserID) REFERENCES Users(UserID) ON DELETE CASCADE
);

CREATE TABLE ProviderServices (
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
);

CREATE TABLE ProviderAvailability (
    ProviderID INT PRIMARY KEY,
    StartTime TIME NOT NULL DEFAULT '09:00:00',
    EndTime TIME NOT NULL DEFAULT '20:00:00',
    FOREIGN KEY (ProviderID) REFERENCES Users(UserID) ON DELETE CASCADE
);

CREATE TABLE ProviderAppointments (
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
);

-- ============================================================
-- 2) CATALOG / CART / ORDERS
-- ============================================================

CREATE TABLE Products (
    ProductID INT AUTO_INCREMENT PRIMARY KEY,
    SellerID INT NULL,
    Name VARCHAR(150) NOT NULL,
    PetCategory VARCHAR(50),
    ProductCategory VARCHAR(50),
    Description TEXT,
    Price DECIMAL(10,2) NOT NULL,
    StockQuantity INT NOT NULL DEFAULT 0,
    ImageURL VARCHAR(500),
    Status VARCHAR(20) NOT NULL DEFAULT 'Active',
    FOREIGN KEY (SellerID) REFERENCES Sellers(UserID) ON DELETE SET NULL
);

CREATE TABLE Carts (
    CartID INT AUTO_INCREMENT PRIMARY KEY,
    CustomerID INT NOT NULL UNIQUE,
    TotalPrice DECIMAL(10,2) DEFAULT 0.00,
    FOREIGN KEY (CustomerID) REFERENCES Users(UserID) ON DELETE CASCADE
);

CREATE TABLE CartItems (
    CartItemID INT AUTO_INCREMENT PRIMARY KEY,
    CartID INT NOT NULL,
    ProductID INT NOT NULL,
    Quantity INT NOT NULL DEFAULT 1,
    Subtotal DECIMAL(10,2) DEFAULT 0.00,
    FOREIGN KEY (CartID) REFERENCES Carts(CartID) ON DELETE CASCADE,
    FOREIGN KEY (ProductID) REFERENCES Products(ProductID) ON DELETE CASCADE
);

CREATE TABLE Orders (
    OrderID INT AUTO_INCREMENT PRIMARY KEY,
    CustomerID INT NOT NULL,
    ShippingAddress TEXT,
    OrderDate DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    TotalAmount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    OrderStatus VARCHAR(20) NOT NULL DEFAULT 'Pending',
    FOREIGN KEY (CustomerID) REFERENCES Users(UserID) ON DELETE CASCADE
);

CREATE TABLE OrderItems (
    OrderItemID INT AUTO_INCREMENT PRIMARY KEY,
    OrderID INT NOT NULL,
    ProductID INT NOT NULL,
    Quantity INT NOT NULL DEFAULT 1,
    PriceAtPurchase DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    FOREIGN KEY (OrderID) REFERENCES Orders(OrderID) ON DELETE CASCADE,
    FOREIGN KEY (ProductID) REFERENCES Products(ProductID) ON DELETE CASCADE
);

-- ============================================================
-- 3) OFFERS / NOTIFICATIONS
-- ============================================================

CREATE TABLE Offers (
    OfferID INT AUTO_INCREMENT PRIMARY KEY,
    OfferCode VARCHAR(50) NOT NULL UNIQUE,
    DiscountPercent INT NOT NULL,
    ValidFrom DATETIME NOT NULL,
    ValidUntil DATETIME NOT NULL,
    TargetUserID INT NULL,
    AppliesToCategory VARCHAR(50) NULL,
    MaxUsesPerUser INT NULL,
    MaxTotalUses INT NULL,
    IsActive TINYINT(1) NOT NULL DEFAULT 1,
    FOREIGN KEY (TargetUserID) REFERENCES Users(UserID) ON DELETE CASCADE
);

CREATE TABLE OfferRedemptions (
    RedemptionID INT AUTO_INCREMENT PRIMARY KEY,
    OfferID INT NOT NULL,
    UserID INT NOT NULL,
    OrderID INT NULL,
    RedeemedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (OfferID) REFERENCES Offers(OfferID) ON DELETE CASCADE,
    FOREIGN KEY (UserID) REFERENCES Users(UserID) ON DELETE CASCADE,
    FOREIGN KEY (OrderID) REFERENCES Orders(OrderID) ON DELETE SET NULL
);

CREATE TABLE Notifications (
    NotificationID INT AUTO_INCREMENT PRIMARY KEY,
    UserID INT NOT NULL,
    Message TEXT NOT NULL,
    IsRead BOOLEAN NOT NULL DEFAULT FALSE,
    CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (UserID) REFERENCES Users(UserID) ON DELETE CASCADE
);

-- ============================================================
-- 4) PERFORMANCE INDEXES
-- ============================================================

CREATE INDEX idx_users_role_status ON Users(Role, AccountStatus);
CREATE INDEX idx_products_status_category ON Products(Status, PetCategory);
CREATE INDEX idx_products_seller ON Products(SellerID);
CREATE INDEX idx_orders_customer_date ON Orders(CustomerID, OrderDate);
CREATE INDEX idx_orders_status_date ON Orders(OrderStatus, OrderDate);
CREATE INDEX idx_order_items_order ON OrderItems(OrderID);
CREATE INDEX idx_order_items_product ON OrderItems(ProductID);
CREATE INDEX idx_notifications_user_created ON Notifications(UserID, CreatedAt);
CREATE INDEX idx_offers_target_validity ON Offers(TargetUserID, ValidFrom, ValidUntil, IsActive);
CREATE INDEX idx_offer_redemptions_offer_user ON OfferRedemptions(OfferID, UserID);

-- ============================================================
-- 5) SEED DATA (STARTER)
-- ============================================================

INSERT INTO Users (Name, Email, Phone, Password, Role, AccountStatus) VALUES
('Super Admin', 'mujahid4110@petnest.com', '01601464611', 'admin123', 'Admin', 'Active'),
('Ali Customer', 'ali.customer@petnest.com', '01711111111', '123456', 'Customer', 'Active'),
('Happy Tails Store', 'sell@happytails.com', '01722222222', 'pass123', 'Seller', 'Active'),
('Dr. Sara Vet', 'sara.vet@petnest.com', '01733333333', 'pass123', 'Vet', 'Active'),
('Paws Home Service', 'service@petnest.com', '01744444444', 'pass123', 'ServiceProvider', 'Active');

INSERT INTO Customers (UserID, ShippingAddress) VALUES
(2, 'Dhaka, Bangladesh');

INSERT INTO Sellers (UserID, StoreName, BusinessName, GovernmentID, PickupAddress, ReturnAddress) VALUES
(3, 'Happy Tails Store', 'Happy Tails Ltd.', 'SELL-9901', 'Dhaka Warehouse', 'Dhaka Return Center');

-- Four additional sellers (UserIDs assume first batch above is IDs 1..5).
INSERT INTO Users (Name, Email, Phone, Password, Role, AccountStatus) VALUES
('Greenwood Pets', 'greenwood.pets@petnest.com', '01810000001', 'pass123', 'Seller', 'Active'),
('Wing & Fin Supply', 'wingfin.supply@petnest.com', '01810000002', 'pass123', 'Seller', 'Active'),
('Creepy Critters Co.', 'critters.co@petnest.com', '01810000003', 'pass123', 'Seller', 'Active'),
('Tiny Friends Mart', 'tinyfriends@petnest.com', '01810000004', 'pass123', 'Seller', 'Active');

INSERT INTO Sellers (UserID, StoreName, BusinessName, GovernmentID, PickupAddress, ReturnAddress) VALUES
(6, 'Greenwood Pets', 'Greenwood Pets LLC', 'SELL-GW01', 'Chattogram Warehouse', 'Chattogram Returns Center'),
(7, 'Wing & Fin Supply', 'Wing and Fin Trading Ltd.', 'SELL-WF02', 'Dhaka Agargaon Hub', 'Dhaka Returns Center'),
(8, 'Creepy Critters Co.', 'Critters Imports BD', 'SELL-CR03', 'Banani Fulfillment Hub', 'Banani Returns'),
(9, 'Tiny Friends Mart', 'Tiny Friends Ltd.', 'SELL-TF04', 'Uttara Warehouse', 'Uttara Returns Center');

INSERT INTO Vets (UserID, ClinicName, Specialization, ExperienceYears, ConsultationFee, GovernmentID, EducationInfo) VALUES
(4, 'PetCare Clinic', 'Small Animal Medicine', 8, 700.00, 'VET-5501', 'DVM, University of Dhaka');

INSERT INTO ServiceProviderProfiles (UserID, BusinessName, ServiceType, Location, Description, AnimalExpertise) VALUES
(5, 'Paws Home Service', 'Grooming & Home Visit', 'Dhaka', 'Doorstep grooming and pet care support.', 'Dog, Cat');

INSERT INTO ProviderServices (ProviderID, ServiceName, PetCategory, Description, Price, DurationMinutes, IsActive) VALUES
(5, 'Full Grooming Session', 'Dog', 'Bath, dry, and nail care.', 40.00, 45, 1);

INSERT INTO ProviderAvailability (ProviderID, StartTime, EndTime) VALUES (5, '09:00:00', '20:00:00');

INSERT INTO Products (SellerID, Name, PetCategory, ProductCategory, Description, Price, StockQuantity, Status) VALUES
(3, 'Premium Grain-Free Cat Food (2kg)', 'Cat', 'Food', 'High protein formula for adult cats.', 24.99, 50, 'Active'),
(3, 'Deluxe Multi-Level Cat Tree', 'Cat', 'Accessories', 'Comfortable climbing and resting tower.', 89.50, 15, 'Active'),
(3, 'High-Protein Adult Dog Kibble (5kg)', 'Dog', 'Food', 'Balanced nutrition for dogs.', 34.99, 40, 'Active'),
(3, 'Orthopedic Memory Foam Dog Bed', 'Dog', 'Accessories', 'Soft support bed for dogs.', 55.00, 20, 'Active'),
(3, 'Tropical Flake Fish Food (100g)', 'Fish', 'Food', 'Daily fish flakes with vitamins.', 8.99, 100, 'Active'),
-- Additional catalog (seller 6 / Greenwood Pets — mixed categories)
(6, 'Coldwater Aquarium Pellets (350g)', 'Fish', 'Food', 'Daily nutrition pellets for coldwater fish.', 13.49, 90, 'Active'),
(6, 'Submersible Aquarium Heater 50W', 'Fish', 'Accessories', 'Adjustable thermostat for small tanks.', 22.95, 45, 'Active'),
(6, 'Canary & Finch Seed Blend (900g)', 'Bird', 'Food', 'Vitamin-fortified small seed blend.', 10.49, 70, 'Active'),
(6, 'Wooden Hanging Bird Swing', 'Bird', 'Accessories', 'Natural perch swing for cages.', 6.49, 120, 'Active'),
(6, 'Dubia Roach Diet Gel (6 cups)', 'Insect', 'Food', 'High-calcium feed for feeders and breeders.', 9.95, 60, 'Active'),
-- Seller 7 / Wing & Fin Supply
(7, 'Interactive Cat Feather Teaser Pole', 'Cat', 'Accessories', 'Replaceable teaser head toy.', 11.49, 75, 'Active'),
(7, 'Braided Cotton Dog Rope (XL)', 'Dog', 'Accessories', 'Dental-friendly tug rope for large dogs.', 15.49, 50, 'Active'),
(7, 'Betta Micro Pellets (60g)', 'Fish', 'Food', 'Floating micro pellets formulated for bettas.', 7.89, 100, 'Active'),
(7, 'Silent Hamster Spinner Wheel 8 in', 'Small Pet', 'Accessories', 'Low-noise upright wheel.', 26.49, 40, 'Active'),
(7, 'Leopard Gecko Calcium + D3 Dust (150g)', 'Reptilian', 'Food', 'Supplement dust for insect feeders.', 12.99, 55, 'Active'),
-- Seller 8 / Creepy Critters Co.
(8, 'Peanut Butter Dental Dog Biscuits (500g)', 'Dog', 'Food', 'Crunchy treats with breath freshener.', 16.89, 65, 'Active'),
(8, 'Hermit Crab Sand Substrate (4 lb)', 'Small Pet', 'Habitat', 'Fine sand mix for nano terrarium setups.', 11.49, 40, 'Active'),
(8, 'Finch Mineral Cuttlebone 2-Pack', 'Bird', 'Accessories', 'Calcium support for cage birds.', 5.89, 100, 'Active'),
(8, 'Beetle Jelly Diet Cups (10 pack)', 'Insect', 'Food', 'Protein jelly cups for beetle species.', 8.25, 80, 'Active'),
(8, 'UVB T5 Terrarium Fixture 24"', 'Reptilian', 'Accessories', 'Mounts standard T5 reptile tubes.', 34.49, 25, 'Active'),
-- Seller 9 / Tiny Friends Mart
(9, 'Compressed Timothy Hay Bale (450g)', 'Small Pet', 'Food', 'High fiber hay for rodents and rabbits.', 9.99, 85, 'Active'),
(9, 'Ceramic Hedgehog Meal Bowl Duo', 'Small Pet', 'Accessories', 'Low-profile dual feeding dish.', 13.49, 50, 'Active'),
(9, 'Wild Bird Suet Cakes (6-pack)', 'Bird', 'Food', 'High-energy suet squares for feeders.', 18.79, 45, 'Active'),
(9, 'Nano Betta Ceramic Tunnel Décor', 'Fish', 'Habitat', 'Low-profile hollow log for nano tanks.', 8.49, 90, 'Active'),
(9, 'Reflective Quick-Release Cat Collar', 'Cat', 'Accessories', 'Bell and breakaway clasp for cats.', 6.89, 110, 'Active'),
(9, 'Organic Paw Butter Balm 2oz', 'Dog', 'Accessories', 'Moisturizing balm for paws and nose.', 10.49, 70, 'Active');

INSERT INTO Carts (CustomerID, TotalPrice) VALUES
(2, 0.00);

INSERT INTO Orders (CustomerID, ShippingAddress, TotalAmount, OrderStatus, OrderDate) VALUES
(2, 'Dhaka, Bangladesh', 120.50, 'Delivered', DATE_SUB(NOW(), INTERVAL 6 DAY)),
(2, 'Dhaka, Bangladesh', 340.00, 'Delivered', DATE_SUB(NOW(), INTERVAL 5 DAY)),
(2, 'Dhaka, Bangladesh', 210.00, 'Delivered', DATE_SUB(NOW(), INTERVAL 4 DAY)),
(2, 'Dhaka, Bangladesh', 450.00, 'Pending', DATE_SUB(NOW(), INTERVAL 1 DAY));

INSERT INTO OrderItems (OrderID, ProductID, Quantity, PriceAtPurchase) VALUES
(1, 1, 2, 24.99),
(1, 3, 1, 34.99),
(2, 2, 2, 89.50),
(3, 4, 3, 55.00),
(4, 5, 5, 8.99);

-- NEST20: one-time per user, available for all users.
INSERT INTO Offers (
    OfferCode, DiscountPercent, ValidFrom, ValidUntil, TargetUserID,
    AppliesToCategory, MaxUsesPerUser, MaxTotalUses, IsActive
) VALUES
('NEST20', 20, NOW(), '2099-12-31 23:59:59', NULL, NULL, 1, NULL, 1),
('CAT10', 10, NOW(), DATE_ADD(NOW(), INTERVAL 30 DAY), NULL, 'Cat', NULL, 500, 1);

INSERT INTO Notifications (UserID, Message) VALUES
(1, 'System initialized successfully.'),
(2, 'Welcome to PetNest!'),
(3, 'Your seller account is active.'),
(4, 'Your vet profile is active.'),
(5, 'Your service provider profile is active.');
