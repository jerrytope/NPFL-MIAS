# NPFL Prediction App — AWS Ubuntu Deployment Guide

## Overview

This guide deploys the NPFL Django app on an AWS EC2 Ubuntu server with:
- **Ubuntu 24.04 LTS**
- **MySQL 8.0** (installed on the same server)
- **Gunicorn** (WSGI server)
- **Nginx** (reverse proxy)
- **Systemd** (auto-restart on crash/reboot)

---

## Part 1: AWS EC2 Setup

### 1.1 Launch EC2 Instance

1. Go to **AWS Console → EC2 → Launch Instance**
2. Name: `npfl-server`
3. **AMI**: Ubuntu 24.04 LTS (Free tier eligible)
4. **Instance type**: `t2.micro` (free tier) or `t2.small` (recommended for production)
5. **Key pair**: Create or select a `.pem` key pair (save it safely!)
6. **Network settings** — Security Group:
   - Allow **SSH** (port 22) — your IP only
   - Allow **HTTP** (port 80) — anywhere
   - Allow **HTTPS** (port 443) — anywhere
   - Allow **MySQL** (port 3306) — your IP only (optional, for remote DB access)
7. **Storage**: 20 GB gp2 (minimum)
8. Click **Launch Instance**

### 1.2 Connect to Your Server

```bash
# From your local machine (Windows PowerShell or terminal)
ssh -i your-key.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

> Replace `YOUR_EC2_PUBLIC_IP` with the actual public IP from AWS Console.

---

## Part 2: Server Setup

### 2.1 Update System

```bash
sudo apt update && sudo apt upgrade -y
```

### 2.2 Install Dependencies

```bash
sudo apt install -y python3 python3-pip python3-venv mysql-server nginx git
```

### 2.3 Configure MySQL

```bash
# Start and secure MySQL
sudo systemctl start mysql
sudo systemctl enable mysql

# Create the database and user
sudo mysql -u root <<EOF
CREATE DATABASE IF NOT EXISTS tope_npfl CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'npfl_user'@'localhost' IDENTIFIED BY 'YourStrongPassword123!';
GRANT ALL PRIVILEGES ON tope_npfl.* TO 'npfl_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
EOF
```

> **IMPORTANT**: Change `YourStrongPassword123!` to your actual password.

### 2.4 Verify MySQL

```bash
mysql -u npfl_user -p -e "SHOW DATABASES;"
# Enter your password when prompted — you should see tope_npfl in the list
```

---

## Part 3: Deploy the Application

### 3.1 Create App Directory

```bash
sudo mkdir -p /opt/npfl/NPFL-MIAS
sudo chown ubuntu:ubuntu /opt/npfl/NPFL-MIAS
cd /opt/npfl/NPFL-MIAS
```

### 3.2 Clone Your Repository

```bash
# Option A: If using Git
git clone YOUR_REPO_URL .

# Option B: If not using Git, use SCP from your local machine
# (run this from your LOCAL machine, not the server)
# scp -i your-key.pem -r .\* ubuntu@YOUR_EC2_PUBLIC_IP:/opt/npfl/NPFL-MIAS/
```

> If you don't have a Git repo, use Option B. Copy everything **except** `myenv/`, `db.sqlite3`, and `.env`.

### 3.3 Create Python Virtual Environment

```bash
cd /opt/npfl/NPFL-MIAS
python3 -m venv venv
source venv/bin/activate
```

### 3.4 Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

### 3.5 Create the `.env` File

```bash
cat > /opt/npfl/NPFL-MIAS/.env << 'EOF'
# Database
DB_NAME=tope_npfl
DB_USER=npfl_user
DB_PASSWORD=YourStrongPassword123!
DB_HOST=localhost
DB_PORT=3306

# Django
SECRET_KEY=change-this-to-a-long-random-string-in-production
DEBUG=False
ALLOWED_HOSTS=YOUR_EC2_PUBLIC_IP,yourdomain.com,localhost

# AI API (if used)
ANTHROPIC_API_KEY=your-api-key-here
ANTHROPIC_BASE_URL=https://agentrouter.org
ANTHROPIC_FALLBACK_BASE_URL=https://ps.air-outer.com
ANTHROPIC_MODEL=gpt-5.6-sol
EOF
```

> **Replace**:
> - `YourStrongPassword123!` with your MySQL password
> - `YOUR_EC2_PUBLIC_IP` with your actual server IP
> - `yourdomain.com` with your domain (or remove it)
> - `change-this-to-a-long-random-string-in-production` — generate one below

Generate a secret key:
```bash
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 3.6 Run Migrations

```bash
cd /opt/npfl/NPFL-MIAS
source venv/bin/activate
python manage.py migrate
```

### 3.7 Create Superuser

```bash
python manage.py createsuperuser
# Follow prompts: username, email, password
```

### 3.8 Collect Static Files

```bash
python manage.py collectstatic --noinput
```

### 3.9 Import Historical Data

```bash
# Copy the Excel file to the server first (from local machine):
# scp -i your-key.pem "plans/NPFL ALL-TIME DATABASE.xlsx" ubuntu@YOUR_EC2_PUBLIC_IP:/opt/npfl/NPFL-MIAS/plans/

# Then import:
python manage.py import_npfl_excel
```

### 3.10 Test with Gunicorn

```bash
cd /opt/npfl/NPFL-MIAS
gunicorn --bind 0.0.0.0:8001 npfl_project.wsgi:application
```

> Visit `http://YOUR_EC2_PUBLIC_IP:8001` — if you see the app, Gunicorn works.
> Press `Ctrl+C` to stop.

---

## Part 4: Systemd Service (Auto-Start)

### 4.1 Create Gunicorn Service

```bash
sudo cat > /etc/systemd/system/npfl.service << 'EOF'
[Unit]
Description=NPFL Django Application
After=network.target mysql.service

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/npfl/NPFL-MIAS
EnvironmentFile=/opt/npfl/NPFL-MIAS/.env
ExecStart=/opt/npfl/NPFL-MIAS/venv/bin/gunicorn \
    --access-logfile /var/log/npfl/access.log \
    --error-logfile /var/log/npfl/error.log \
    --workers 3 \
    --bind 127.0.0.1:8001 \
    npfl_project.wsgi:application
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
```

### 4.2 Create Log Directory and Start Service

```bash
sudo mkdir -p /var/log/npfl
sudo chown ubuntu:ubuntu /var/log/npfl

sudo systemctl daemon-reload
sudo systemctl start npfl
sudo systemctl enable npfl    # auto-start on reboot

# Check status:
sudo systemctl status npfl
```

---

## Part 5: Nginx Reverse Proxy

### 5.1 Create Nginx Config

```bash
sudo cat > /etc/nginx/sites-available/npfl << 'EOF'
server {
    listen 80;
    server_name YOUR_EC2_PUBLIC_IP yourdomain.com;

    client_max_body_size 20M;

    # Static files (CSS, JS, logos)
    location /static/ {
        alias /opt/npfl/NPFL-MIAS/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Logo files
    location /logos/ {
        alias /opt/npfl/NPFL-MIAS/logos/;
        expires 30d;
    }

    # Proxy to Gunicorn
    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }
}
EOF
```

### 5.2 Enable Site and Restart Nginx

```bash
sudo ln -s /etc/nginx/sites-available/npfl /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default   # remove default site
sudo nginx -t                                  # test config
sudo systemctl restart nginx
```

---

## Part 6: Verify Everything Works

```bash
# Check all services are running:
sudo systemctl status nginx
sudo systemctl status npfl
sudo systemctl status mysql

# Test the app:
curl -I http://localhost          # should return 200
curl -I http://YOUR_EC2_PUBLIC_IP # should return 200
```

Open your browser:
- **Dashboard**: `http://YOUR_EC2_PUBLIC_IP/`
- **Supercomputer**: `http://YOUR_EC2_PUBLIC_IP/supercomputer/`
- **Admin Panel**: `http://YOUR_EC2_PUBLIC_IP/admin/`

---

## Part 7: (Optional) Domain + HTTPS

### 7.1 Point Your Domain

In your domain registrar (GoDaddy, Namecheap, etc.), add an **A record**:
- Host: `@` (or `www`)
- Value: `YOUR_EC2_PUBLIC_IP`

### 7.2 Install Certbot (Free SSL)

```bash
sudo apt install -y certbot python3-certbot-nginx

# Get certificate (replace with your domain)
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Auto-renewal is configured automatically
```

---

## Quick Reference — Common Commands

| Action | Command |
|--------|---------|
| Start app | `sudo systemctl start npfl` |
| Stop app | `sudo systemctl stop npfl` |
| Restart app | `sudo systemctl restart npfl` |
| View app logs | `sudo journalctl -u npfl -f` |
| Gunicorn error log | `tail -f /var/log/npfl/error.log` |
| Nginx error log | `tail -f /var/log/nginx/error.log` |
| Restart Nginx | `sudo systemctl restart nginx` |
| Test Nginx config | `sudo nginx -t` |
| Run migrations | `cd /opt/npfl/NPFL-MIAS && source venv/bin/activate && python manage.py migrate` |
| Generate predictions | `cd /opt/npfl/NPFL-MIAS && source venv/bin/activate && python manage.py generate_predictions` |
| Import Excel data | `cd /opt/npfl/NPFL-MIAS && source venv/bin/activate && python manage.py import_npfl_excel` |
| Django shell | `cd /opt/npfl/NPFL-MIAS && source venv/bin/activate && python manage.py shell` |

---

## Deployment Checklist

- [ ] EC2 instance launched with correct security group
- [ ] SSH access working
- [ ] MySQL installed, database and user created
- [ ] Code deployed to `/opt/npfl/NPFL-MIAS`
- [ ] `.env` file configured with production values
- [ ] `DEBUG=False` in `.env`
- [ ] `SECRET_KEY` changed to a random string
- [ ] `ALLOWED_HOSTS` set to your IP/domain
- [ ] Migrations applied
- [ ] Superuser created
- [ ] Static files collected (`collectstatic`)
- [ ] Historical data imported
- [ ] Gunicorn service running
- [ ] Nginx configured and serving traffic
- [ ] App accessible via browser
- [ ] (Optional) Domain pointed and SSL configured
