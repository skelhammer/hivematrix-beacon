import os
import json
import datetime
import requests
import logging
from flask import Flask, render_template, jsonify, abort, redirect, url_for, request, flash
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

# Load environment variables
load_dotenv('.flaskenv')

# --- Configuration ---
STATIC_DIR = "static"
AUTO_REFRESH_INTERVAL_SECONDS = 30

# Professional Services Group ID from Freshservice
PROFESSIONAL_SERVICES_GROUP_ID = 19000234009

# --- View Configuration ---
SUPPORTED_VIEWS = {
    "helpdesk": "Helpdesk",
    "professional-services": "Professional Services"
}
DEFAULT_VIEW_SLUG = "helpdesk"

INDEX_TEMPLATE = "index.html"

app = Flask(__name__, static_folder=STATIC_DIR)
app.secret_key = os.urandom(24)

# Configure logging level from environment
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
app.logger.setLevel(getattr(logging, log_level, logging.INFO))

# Apply ProxyFix for Nexus proxy compatibility
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_prefix=1
)

# Load services configuration
try:
    with open('services.json') as f:
        services_config = json.load(f)
        app.config['SERVICES'] = services_config
        app.logger.info(f"Loaded {len(services_config)} services from services.json")
except FileNotFoundError:
    app.logger.warning("services.json not found. Service calls will not work.")
    app.config['SERVICES'] = {}

# Service configuration from environment
app.config['SERVICE_NAME'] = os.environ.get('SERVICE_NAME', 'beacon')
app.config['CORE_SERVICE_URL'] = os.environ.get('CORE_SERVICE_URL', 'http://localhost:5000')

if not app.debug:
    app.logger.setLevel(logging.INFO)
else:
    app.logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s '
    '[in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(handler)

# Agent mapping for display
AGENT_MAPPING = {}

# Cache for Freshservice domain
_freshservice_domain = None


def get_service_token(target_service):
    """Get a service token from Core for authenticated service-to-service calls."""
    core_url = app.config.get('CORE_SERVICE_URL')
    calling_service = app.config.get('SERVICE_NAME', 'beacon')

    try:
        response = requests.post(
            f"{core_url}/service-token",
            json={
                'calling_service': calling_service,
                'target_service': target_service
            },
            timeout=5
        )

        if response.status_code == 200:
            return response.json().get('token')
        else:
            app.logger.error(f"Failed to get service token: {response.status_code}")
            return None
    except Exception as e:
        app.logger.error(f"Error getting service token: {e}")
        return None


def call_service(service_name, path, method='GET', **kwargs):
    """Make an authenticated request to another HiveMatrix service."""
    services = app.config.get('SERVICES', {})

    if service_name not in services:
        app.logger.error(f"Service '{service_name}' not found in services.json")
        return None

    service_url = services[service_name]['url']
    token = get_service_token(service_name)

    if not token:
        app.logger.error(f"Could not get token for {service_name}")
        return None

    url = f"{service_url}{path}"
    headers = kwargs.pop('headers', {})
    headers['Authorization'] = f'Bearer {token}'

    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            timeout=kwargs.pop('timeout', 30),
            **kwargs
        )
        return response
    except Exception as e:
        app.logger.error(f"Error calling {service_name}{path}: {e}")
        return None


def get_freshservice_domain():
    """Get Freshservice domain from Codex configuration."""
    global _freshservice_domain

    if _freshservice_domain:
        return _freshservice_domain

    # Try to get from Codex's config endpoint
    try:
        response = call_service('codex', '/api/config/freshservice_domain')
        if response and response.status_code == 200:
            _freshservice_domain = response.json().get('value', 'freshservice.com')
            return _freshservice_domain
    except:
        pass

    # Fallback default
    return 'freshservice.com'


def load_agent_mapping():
    """Load agent mapping from Codex API."""
    global AGENT_MAPPING

    response = call_service('codex', '/api/freshservice/agents')

    if response and response.status_code == 200:
        agents = response.json()
        AGENT_MAPPING = {agent['id']: agent['name'] for agent in agents}
        app.logger.info(f"Loaded {len(AGENT_MAPPING)} agents from Codex")
    else:
        app.logger.warning("Failed to load agents from Codex")


def fetch_tickets_from_codex():
    """Fetch active tickets from Codex API."""
    response = call_service('codex', '/api/tickets/active')

    if response and response.status_code == 200:
        return response.json()
    else:
        app.logger.error("Failed to fetch tickets from Codex")
        return None


def filter_tickets_by_view(tickets, view_slug):
    """Filter a list of tickets by view (helpdesk vs professional-services)."""
    if not tickets:
        return []

    filtered = []
    for ticket in tickets:
        group_id = ticket.get('group_id')
        is_prof_services = (group_id == PROFESSIONAL_SERVICES_GROUP_ID)

        if view_slug == 'professional-services' and is_prof_services:
            filtered.append(ticket)
        elif view_slug == 'helpdesk' and not is_prof_services:
            filtered.append(ticket)

    return filtered


def filter_tickets_by_agent(tickets, agent_id):
    """Filter tickets by agent ID."""
    if not tickets or not agent_id:
        return tickets

    return [t for t in tickets if t.get('responder_id') == agent_id]


def get_tickets_for_view(view_slug, agent_id=None):
    """Get tickets from Codex filtered by view and optionally by agent."""
    # Load agent mapping if not loaded
    if not AGENT_MAPPING:
        load_agent_mapping()

    data = fetch_tickets_from_codex()

    if not data:
        return [], [], [], []

    # Extract sections from Codex response
    section1 = data.get('section1', [])
    section2 = data.get('section2', [])
    section3 = data.get('section3', [])
    section4 = data.get('section4', [])

    # Filter by view
    s1 = filter_tickets_by_view(section1, view_slug)
    s2 = filter_tickets_by_view(section2, view_slug)
    s3 = filter_tickets_by_view(section3, view_slug)
    s4 = filter_tickets_by_view(section4, view_slug)

    # Filter by agent if specified
    if agent_id:
        s1 = filter_tickets_by_agent(s1, agent_id)
        s2 = filter_tickets_by_agent(s2, agent_id)
        s3 = filter_tickets_by_agent(s3, agent_id)
        s4 = filter_tickets_by_agent(s4, agent_id)

    return s1, s2, s3, s4


# --- Routes ---

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings page for Beacon configuration."""
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update_interval':
            flash('Refresh interval is controlled by client-side settings.', 'info')
        return redirect(url_for('settings'))

    # Check Codex connection status
    response = call_service('codex', '/api/health')
    scheduler_status = "Running" if response and response.status_code == 200 else "Stopped"

    return render_template('settings.html',
                           scheduler_status=scheduler_status,
                           poll_interval=AUTO_REFRESH_INTERVAL_SECONDS)


@app.route('/')
def dashboard_default():
    """Redirect to default view."""
    return redirect(DEFAULT_VIEW_SLUG)


@app.route('/<view_slug>')
def dashboard_typed(view_slug):
    """Main dashboard route for a specific view."""
    if view_slug not in SUPPORTED_VIEWS:
        abort(404, description=f"Unsupported view: {view_slug}")

    agent_id = request.args.get('agent_id', type=int)
    current_view_display = SUPPORTED_VIEWS[view_slug]

    app.logger.info(f"Loading dashboard for view: {current_view_display} (slug: {view_slug})")

    s1_items, s2_items, s3_items, s4_items = get_tickets_for_view(view_slug, agent_id=agent_id)

    generated_time_utc = datetime.datetime.now(datetime.timezone.utc)
    dashboard_generated_time_iso = generated_time_utc.isoformat()

    section1_name = f"Open {current_view_display} Tickets"
    section2_name = "Customer Replied"
    section3_name = "Needs Agent / Update Overdue"
    section4_name = f"Other Active {current_view_display} Tickets"

    # Get Freshservice domain for ticket links
    freshservice_domain = get_freshservice_domain()

    return render_template(INDEX_TEMPLATE,
                           s1_items=s1_items,
                           s2_items=s2_items,
                           s3_items=s3_items,
                           s4_items=s4_items,
                           dashboard_generated_time_iso=dashboard_generated_time_iso,
                           auto_refresh_ms=AUTO_REFRESH_INTERVAL_SECONDS * 1000,
                           freshservice_base_url=f"https://{freshservice_domain}/a/tickets/",
                           current_view_slug=view_slug,
                           current_view_display=current_view_display,
                           supported_views=SUPPORTED_VIEWS,
                           page_title_display=current_view_display,
                           section1_name=section1_name,
                           section2_name=section2_name,
                           section3_name=section3_name,
                           section4_name=section4_name,
                           agent_mapping=AGENT_MAPPING,
                           selected_agent_id=agent_id)


@app.route('/api/tickets/<view_slug>')
def api_tickets(view_slug):
    """API endpoint for ticket data."""
    if view_slug not in SUPPORTED_VIEWS:
        return jsonify({"error": f"Unsupported view: {view_slug}"}), 404

    agent_id = request.args.get('agent_id', type=int)
    current_view_display = SUPPORTED_VIEWS[view_slug]

    app.logger.debug(f"API: /api/tickets/{view_slug} called")

    s1_items, s2_items, s3_items, s4_items = get_tickets_for_view(view_slug, agent_id=agent_id)

    response_data = {
        's1_items': s1_items,
        's2_items': s2_items,
        's3_items': s3_items,
        's4_items': s4_items,
        'total_active_items': len(s1_items) + len(s2_items) + len(s3_items) + len(s4_items),
        'dashboard_generated_time_iso': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'view': current_view_display,
        'section1_name_js': f"Open {current_view_display} Tickets",
        'section2_name_js': "Customer Replied",
        'section3_name_js': "Needs Agent / Update Overdue",
        'section4_name_js': f"Other Active {current_view_display} Tickets"
    }

    app.logger.debug(f"API: Returning {response_data['total_active_items']} total items")
    return jsonify(response_data)


if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(script_dir, 'templates')

    for dir_path in [templates_dir, STATIC_DIR]:
        abs_dir_path = os.path.abspath(dir_path)
        if not os.path.exists(abs_dir_path):
            try:
                os.makedirs(abs_dir_path)
                app.logger.info(f"Created directory at {abs_dir_path}.")
            except OSError as e:
                app.logger.error(f"Failed to create directory {abs_dir_path}: {e}")
                exit(f"Error: Could not create essential directory {abs_dir_path}. Exiting.")

    # Load agent mapping from Codex
    load_agent_mapping()

    app.logger.info(f"Starting Beacon - Ticket Dashboard")
    app.logger.info(f"Supported views: {SUPPORTED_VIEWS}")

    app.run(host='0.0.0.0', port=5001, debug=False)
