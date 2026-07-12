# Leoxur Income Tracker - Production Deployment & Monitoring Manual

This deployment guide is designed for administrators, operations engineers, and laymen. It outlines how to deploy the Leoxur Income Tracker application inside a multi-container Docker Compose architecture on any cloud virtual machine (AWS EC2, Google Compute Engine, or Azure VM) with a custom domain, HTTPS/SSL, MySQL database storage, and a Prometheus/Grafana hardware telemetry stack.

---

## 🏗️ Dockerized Services Architecture

When you start the application on a cloud server, the following 8 components run simultaneously, separated inside Docker isolation:

1. **`leoxur_web` (Django + Gunicorn)**: Runs the core income tracker application and handles all page requests, ledger computations, and database reads/writes.
2. **`leoxur_db` (MySQL Database)**: Stores all database records (transactions, users, categories, budgets, and reminders) persistently.
3. **`leoxur_nginx` (Reverse Proxy)**: A high-performance web router that handles secure incoming SSL traffic (HTTPS port 443) and serves stylesheet files directly to users.
4. **`leoxur_certbot` (Let's Encrypt Renewals)**: Automatically requests and renews security certificates for your custom domain.
5. **`leoxur_prometheus` (Metrics Collector)**: Scrapes resource logs (CPU, RAM, container lifespans) and feeds them into the visualization dashboard.
6. **`leoxur_grafana` (Analytics UI)**: Hosts a dashboard to graph CPU, memory, filesystem, and network stats over time.
7. **`leoxur_node_exporter` (Host Scraper)**: Exposes hardware metrics of the underlying virtual machine.
8. **`leoxur_cadvisor` (Container Scraper)**: Exposes performance statistics and up/down status logs for all docker containers.

---

## 🌐 1. Preparing Your Cloud VM

Before launching the containers, set up your server in AWS, GCP, or Azure.

### AWS EC2
1. Launch an EC2 Instance (select **Ubuntu Server 22.04 LTS**).
2. Choose instance size `t3.small` or `t3.medium` (recommended for Prometheus/Grafana memory scraping).
3. Under **Security Group Config**, configure inbound firewall rules to allow:
   - **Port 22**: SSH access (your IP only).
   - **Port 80**: HTTP access (anywhere).
   - **Port 443**: HTTPS access (anywhere).
   - **Port 3306**: MySQL database (restricted to your IP only, if using external client UI database tools like TablePlus or DBeaver).
   - **Port 3000**: Grafana UI (restricted to your IP only, if checking metrics visually).
4. Allocate an **Elastic IP** and associate it with your instance.

### GCP Compute Engine / Azure VM
1. Create a VM instance using **Ubuntu Server 22.04 LTS**.
2. Configure **Firewall Rules** to allow TCP traffic on ports **80**, **443**, **3306**, and **3000**.
3. Allocate a static public IP address to the instance.

---

## 🔗 2. Configure Domain Records

To run on HTTPS, map your domain name to your cloud server's static IP.
1. Log in to your domain provider (e.g. GoDaddy, Namecheap, Google Domains).
2. Go to your **DNS Zone Editor**.
3. Create an **A Record**:
   - **Host/Name**: `tracker` (for `tracker.yourdomain.com`) or `@` (for main domain `yourdomain.com`).
   - **Value/Points To**: Your Cloud VM Static IP address.
   - **TTL**: `600` or `1 Hour`.

---

## 🛠️ 3. Install Docker & Git

Log in to your Cloud VM via SSH and run these commands to install dependencies:

```bash
# Update local packages list
sudo apt-get update && sudo apt-get upgrade -y

# Install Docker
sudo apt-get install -y docker.io docker-compose

# Start and enable Docker service on boot
sudo systemctl start docker
sudo systemctl enable docker

# Check Docker version
docker --version
docker-compose --version
```

---

## 🚀 4. Setting up Environmental Configs

Clone the repository and create an `.env` file in the project root directory containing the required secrets.

```bash
git clone https://github.com/leoxurDev/LeoxurIncomeTracker.git
cd LeoxurIncomeTracker

# Create .env configuration file
nano .env
```

Add the following environment parameters (adjust values accordingly):

```env
# DATABASE SETTINGS
DB_NAME=income_tracker
DB_USER=leoxur_admin
DB_PASSWORD=YOUR_SECURE_PASSWORD
DB_ROOT_PASSWORD=YOUR_SECURE_ROOT_PASSWORD

# SECURITY
SECRET_KEY=django-production-secure-key-choose-random-chars
ALLOWED_HOSTS=tracker.yourdomain.com,localhost,127.0.0.1

# SMTP EMAIL CONFIGURATION
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-gmail-app-password
EMAIL_USE_TLS=True
```
Press `Ctrl+O` and `Enter` to save, then `Ctrl+X` to exit nano.

---

## 🔐 5. Requesting SSL & Starting Nginx

We use the automated `init-ssl.sh` script to verify domain ownership and configure LetsEncrypt HTTPS certificates:

```bash
# Make script executable
chmod +x init-ssl.sh

# Run SSL bootstrap sequence
sudo ./init-ssl.sh
```

**What the script does under the hood:**
1. Prompts for your domain name (e.g. `tracker.yourdomain.com`) and contact email.
2. Updates `nginx.conf` with your domain variables.
3. Generates a placeholder self-signed SSL key structure.
4. Boots up the Nginx router container.
5. Invokes Certbot to request real Let's Encrypt certificates.
6. Replaces the self-signed key placeholder and reloads Nginx dynamically.

Once finished, open your browser and navigate to `https://tracker.yourdomain.com`. You should see the secure padlock icon and the Leoxur Login page!

---

## 📈 6. Prometheus & Grafana Configuration

To monitor host resources (CPU, Memory, Disk) and docker status logs visually:

1. Open your browser and head to `http://your-server-ip:3000`.
2. Log in with the default Grafana credentials:
   - **Username**: `admin`
   - **Password**: `admin` (it will immediately prompt you to change this).
3. **Add Prometheus as a Data Source**:
   - Go to **Connections > Data Sources > Add Data Source**.
   - Select **Prometheus**.
   - Set **URL** to: `http://prometheus:9090`
   - Scroll to the bottom and click **Save & Test**. You should see a green "Data source is working" notification.
4. **Import Node Exporter Dashboard**:
   - Go to **Dashboards > New > Import**.
   - In the **Import via grafana.com** text input, paste the ID: `1860` (the standard official Node Exporter Full dashboard ID) and click **Load**.
   - Select your **Prometheus** data source inside the dropdown and click **Import**.
   - You now have a dashboard graphing CPU utilization, memory, disks, filesystem reads, and network traffic.
5. **Import cAdvisor Container Dashboard**:
   - Go to **Dashboards > New > Import**.
   - Input ID: `14282` (standard cAdvisor container monitoring dashboard ID) or design a custom pane to track individual container statuses (`container_state` or `container_cpu_usage_seconds_total`).

---

## 🗄️ 7. Accessing the MySQL Database

### From Inside the Container Command Line
If you need to perform raw SQL queries directly inside your server shell:
```bash
# Exec into MySQL container
docker exec -it leoxur_db mysql -u leoxur_admin -p
```
It will prompt for your configured `DB_PASSWORD`. Once entered, run queries like:
```sql
USE income_tracker;
SHOW TABLES;
SELECT * FROM tracker_transaction LIMIT 10;
```

### From an External GUI Tool (DBeaver, TablePlus, Navicat)
1. Ensure your Cloud VM security group/firewall allows inbound traffic on port **3306** (restricted to your personal home/office IP for safety).
2. Open your client database tool.
3. Create a new **MySQL Connection**:
   - **Host**: Your Cloud VM Static IP address.
   - **Port**: `3306`
   - **Database**: `income_tracker` (or your configured `DB_NAME`).
   - **Username**: `leoxur_admin` (or your configured `DB_USER`).
   - **Password**: Your configured database password.
4. Connect. You can now visually query, export, and manage your transactional database schema.

---

## 📧 8. Setting up System Monitoring Alerts (SMTP)

To monitor system hardware utilization and receive warning emails when containers crash or CPU/RAM/Disk stays above 80%, schedule the built-in system check.

### Testing Alerts Manually
Run the Django check command inside the running web container to test telemetry functionality:
```bash
docker exec -it leoxur_web python3 manage.py monitor_system
```

### Automating the Checks via Cron Task
To run system checks every 10 minutes in the background:
1. Open your host machine's cron tab editor:
   ```bash
   crontab -e
   ```
2. Add the following line at the bottom of the file (this commands the host to run the monitor system task inside the container):
   ```cron
   */10 * * * * docker exec leoxur_web python3 manage.py monitor_system >/dev/null 2>&1
   ```
3. Save and close. The script will evaluate host hardware resources and container states every 10 minutes. If resource thresholds breach 80% or a container crashes, a styled Apple-themed email warning is immediately sent to all superuser admins. When performance recovers, a corresponding resolved notification is dispatched.
