# RetailFlow — Modern Retail ERP & Point of Sale (POS)

RetailFlow is a multi-tenant Retail ERP and Point-of-Sale (POS) management system built with **Django 5** and **PostgreSQL**. It delivers an end-to-end platform for retail businesses, covering inventory tracking, purchase management, supplier relations, employee role management, and an interactive, touchscreen-friendly POS terminal.

---

## 🚀 Key Features

### 🛒 Point of Sale (POS)
- **Touchscreen & Barcode Friendly**: Fast product search by name, SKU, or barcode with category filtering.
- **Dynamic Shopping Cart**: Real-time quantity adjustments, discounts, and tax computation.
- **Hold & Recall Bills**: Park customer carts and resume them at any time to keep checkout lines moving.
- **Multiple Payment Methods**: Support for Cash (with change calculation), Card, and UPI / QR codes.
- **Atomic Checkout & Inventory Sync**: Completing a sale automatically performs a real-time **Stock OUT** transaction in the inventory with duplicate-checkout prevention.
- **Thermal Receipts**: Printable customer receipts formatted for standard 80mm thermal receipt printers.
- **Sales History & Reports**: Comprehensive transaction log with filters by date, customer, and receipt number.

### 📦 Inventory & Products
- **Real-Time Stock Tracking**: Accurate on-hand quantities across all product variants.
- **Stock Movements**: Automated audit trail of Stock IN (purchases) and Stock OUT (POS sales, adjustments).
- **Product Catalog**: Category management, pricing rules, SKUs, and barcodes.

### 🚚 Purchasing & Supplier Management
- **Vendor Tracking**: Manage supplier records, contact details, and order history.
- **Purchase Orders**: Record supplier invoices and automatically replenish stock levels upon receipt.

### 👥 Multi-Tenancy & Employee Access Control (RBAC)
- **Tenant Isolation**: Secure company data segregation powered by tenant middleware and context managers.
- **Role-Based Permissions**: Distinct dashboards and permissions for **Managers**, **Inventory Staff**, and **Cashiers**.
- **Cashier Isolation**: Enforced by dedicated middleware to restrict cashiers strictly to the POS terminal, sales history, and daily reports.

---

## 🛠️ Tech Stack

- **Backend Framework**: Python 3.12+, Django 5.2
- **Database**: PostgreSQL (via `psycopg3`)
- **Frontend**: Responsive HTML5, CSS3, Vanilla JavaScript, Modal UI system
- **Reporting & Export**: OpenPyXL for data handling

---

## 📁 Project Structure

```text
Retailflow/
├── .gitignore
├── README.md
├── requirements.txt
├── src/
│   └── retailflow/
│       ├── manage.py
│       ├── retailflow/         # Root settings, routing, and WSGI/ASGI
│       ├── accounts/           # User authentication and registration
│       ├── company/            # Multi-tenant company context and middleware
│       ├── employees/          # Employee management, roles, and login routing
│       ├── products/           # Product catalog, categories, and SKU tracking
│       ├── inventory/          # Stock levels and inventory movement logs
│       ├── suppliers/          # Supplier directory and contact management
│       ├── purchases/          # Purchase orders and stock replenishment
│       ├── pos/                # POS terminal, cart, checkout service, receipts
│       ├── landing/            # Public landing page
│       └── templates/          # Global UI templates and app layouts
└── venv/                       # (Excluded from Git)
```

---

## ⚙️ Getting Started

### 1. Prerequisites
- **Python 3.12+**
- **PostgreSQL 14+**
- **Git**

### 2. Clone the Repository
```bash
git clone https://github.com/Shabeeb-ops/Retailflow.git
cd Retailflow
```

### 3. Create & Activate Virtual Environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Configure PostgreSQL Database
Create a PostgreSQL database for RetailFlow:
```sql
CREATE DATABASE retail_flow_db;
```

Update your database credentials in `src/retailflow/retailflow/settings.py` if different from default:
```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "retail_flow_db",
        "USER": "postgres",
        "PASSWORD": "your_password",
        "HOST": "localhost",
        "PORT": "5432",
    }
}
```

### 6. Run Migrations
```bash
python src/retailflow/manage.py migrate
```

### 7. Create a Superuser
```bash
python src/retailflow/manage.py createsuperuser
```

### 8. Run the Development Server
```bash
python src/retailflow/manage.py runserver
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

---

## 🧪 Running Automated Tests

Run the test suite across all apps:
```bash
python src/retailflow/manage.py test company employees products inventory purchases suppliers accounts pos
```

---

## 🔒 Security & Best Practices

- **Zero Leak Multi-Tenancy**: Data queries are strictly scoped to the active tenant/company.
- **Atomic Operations**: All financial checkouts and stock mutations run within database transactions (`transaction.atomic`).
- **Role Isolation**: Non-cashier routes automatically reject unauthorized employee access.

---

## 📄 License
This project is proprietary and developed for retail business management.

