import os
import json
import datetime
import requests
import logging
import sys
from flask import Flask, render_template, jsonify, abort, redirect, url_for, request, flash
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from app.rate_limit_key import get_user_id_or_ip
from dotenv import load_dotenv
from app.version import VERSION, SERVICE_NAME
from app.service_client import call_service

# Health check library
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from health_check import HealthChecker

# Load environment variables
load_dotenv('.flaskenv')

# --- Configuration ---
STATIC_DIR = "static"
AUTO_REFRESH_INTERVAL_SECONDS = 300  # 5 minutes to match Codex light ticket sync schedule

# Professional Services Group ID (configured per PSA provider)
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

# Enable structured JSON logging with correlation IDs
# Set ENABLE_JSON_LOGGING=false in environment to disable for development
enable_json = os.environ.get("ENABLE_JSON_LOGGING", "true").lower() in ("true", "1", "yes")
if enable_json:
    from app.structured_logger import setup_structured_logging
    setup_structured_logging(app, enable_json=True)

# Context processor to inject version into all templates
@app.context_processor
def inject_version():
    return {
        'app_version': VERSION,
        'app_service_name': SERVICE_NAME
    }

# Register RFC 7807 error handlers for consistent API error responses
from app.error_responses import (
    internal_server_error,
    not_found,
    bad_request,
    unauthorized,
    forbidden,
    service_unavailable
)

@app.errorhandler(400)
def handle_bad_request(e):
    """Handle 400 Bad Request errors"""
    return bad_request(detail=str(e))

@app.errorhandler(401)
def handle_unauthorized(e):
    """Handle 401 Unauthorized errors"""
    return unauthorized(detail=str(e))

@app.errorhandler(403)
def handle_forbidden(e):
    """Handle 403 Forbidden errors"""
    return forbidden(detail=str(e))

@app.errorhandler(404)
def handle_not_found(e):
    """Handle 404 Not Found errors"""
    return not_found(detail=str(e))

@app.errorhandler(500)
def handle_internal_error(e):
    """Handle 500 Internal Server Error"""
    app.logger.error(f"Internal server error: {e}")
    return internal_server_error()

@app.errorhandler(503)
def handle_service_unavailable(e):
    """Handle 503 Service Unavailable errors"""
    return service_unavailable(detail=str(e))

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    """Catch-all handler for unexpected exceptions"""
    app.logger.exception(f"Unexpected error: {e}")
    return internal_server_error(detail="An unexpected error occurred")

# Apply ProxyFix for Nexus proxy compatibility
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_prefix=1
)

# Initialize rate limiter
limiter = Limiter(
    get_user_id_or_ip,  # Per-user rate limiting
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
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

# Enable structured JSON logging with correlation IDs
# Set ENABLE_JSON_LOGGING=false in environment to disable for development
enable_json = os.environ.get("ENABLE_JSON_LOGGING", "true").lower() in ("true", "1", "yes")
if enable_json:
    from app.structured_logger import setup_structured_logging
    setup_structured_logging(app, enable_json=True)
else:
    app.logger.setLevel(logging.DEBUG)

# Enable structured JSON logging with correlation IDs
# Set ENABLE_JSON_LOGGING=false in environment to disable for development
enable_json = os.environ.get("ENABLE_JSON_LOGGING", "true").lower() in ("true", "1", "yes")
if enable_json:
    from app.structured_logger import setup_structured_logging
    setup_structured_logging(app, enable_json=True)

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s '
    '[in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(handler)

# Agent mapping for display
AGENT_MAPPING = {}

# Cache for PSA ticket base URL
_psa_ticket_base_url = None


def get_psa_ticket_base_url():
    """Get PSA ticket base URL from Codex configuration."""
    global _psa_ticket_base_url

    if _psa_ticket_base_url:
        return _psa_ticket_base_url

    # Try to get from Codex's PSA config endpoint
    try:
        response = call_service('codex', '/api/psa/config')
        if response and response.status_code == 200:
            data = response.json()
            default_provider = data.get('default_provider')
            providers = data.get('providers', {})

            if default_provider and default_provider in providers:
                # Get ticket URL template and convert to base URL
                template = providers[default_provider].get('ticket_url_template', '')
                if template:
                    # Remove the {ticket_id} placeholder to get base URL
                    _psa_ticket_base_url = template.replace('{ticket_id}', '')
                    return _psa_ticket_base_url
    except (requests.RequestException, ValueError, KeyError) as e:
        app.logger.error(f"Could not fetch PSA config from Codex: {e}")

    # No PSA configured - return None to indicate failure
    app.logger.warning("No PSA provider configured - ticket links will not work")
    return None


def load_agent_mapping():
    """Load agent mapping from Codex API."""
    global AGENT_MAPPING

    response = call_service('codex', '/api/psa/agents')

    if response and response.status_code == 200:
        agents = response.json()
        # Use external_id (PSA provider ID) not internal database id
        # Only include active agents in the dropdown
        AGENT_MAPPING = {agent['external_id']: agent['name'] for agent in agents if agent.get('active', True)}
        app.logger.info(f"Loaded {len(AGENT_MAPPING)} active agents from Codex")
    else:
        app.logger.warning("Failed to load agents from Codex")


def fetch_tickets_from_codex():
    """Fetch active tickets from Codex API."""
    response = call_service('codex', '/api/tickets/active')

    if response and response.status_code == 200:
        data = response.json()
        # Extract last_sync_time from Codex response
        return data, data.get('last_sync_time')
    else:
        app.logger.error("Failed to fetch tickets from Codex")
        return None, None


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
    """Filter tickets by agent ID (external_id from PSA system)."""
    if not tickets or not agent_id:
        return tickets

    # Ensure type consistency - convert both to int for comparison
    agent_id = int(agent_id)
    return [t for t in tickets if t.get('responder_id') == agent_id]


def get_tickets_for_view(view_slug, agent_id=None):
    """Get tickets from Codex filtered by view and optionally by agent."""
    # Load agent mapping if not loaded
    if not AGENT_MAPPING:
        load_agent_mapping()

    data, last_sync_time = fetch_tickets_from_codex()

    if not data:
        return [], [], [], [], None

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

    return s1, s2, s3, s4, last_sync_time


# Configure OpenAPI/Swagger documentation
from flasgger import Swagger

swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec',
            "route": '/apispec.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/docs"
}

swagger_template = {
    "info": {
        "title": "HiveMatrix Beacon API",
        "description": "API documentation for HiveMatrix Beacon - Real-time ticket dashboard with PSA integration",
        "version": VERSION
    },
    "securityDefinitions": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": "JWT Authorization header using the Bearer scheme. Example: 'Authorization: Bearer {token}'"
        }
    },
    "security": [
        {
            "Bearer": []
        }
    ]
}

Swagger(app, config=swagger_config, template=swagger_template)

# --- Routes ---

@app.route('/')
@limiter.exempt
def dashboard_default():
    """Redirect to default view."""
    return redirect(DEFAULT_VIEW_SLUG)


@app.route('/<view_slug>')
def dashboard_typed(view_slug):
    """Main dashboard route for a specific view (authenticated)."""
    if view_slug not in SUPPORTED_VIEWS:
        abort(404, description=f"Unsupported view: {view_slug}")

    agent_id = request.args.get('agent_id', type=int)
    current_view_display = SUPPORTED_VIEWS[view_slug]

    app.logger.info(f"Loading dashboard for view: {current_view_display} (slug: {view_slug})")

    s1_items, s2_items, s3_items, s4_items, last_sync_time = get_tickets_for_view(view_slug, agent_id=agent_id)

    # Use last_sync_time from Codex if available, otherwise use current time
    if last_sync_time:
        dashboard_generated_time_iso = last_sync_time
    else:
        generated_time_utc = datetime.datetime.now(datetime.timezone.utc)
        dashboard_generated_time_iso = generated_time_utc.isoformat()

    section1_name = f"Open {current_view_display} Tickets"
    section2_name = "Customer Replied"
    section3_name = "Needs Agent / Update Overdue"
    section4_name = f"Other Active {current_view_display} Tickets"

    # Get PSA ticket base URL for ticket links
    ticket_base_url = get_psa_ticket_base_url()

    return render_template(INDEX_TEMPLATE,
                           s1_items=s1_items,
                           s2_items=s2_items,
                           s3_items=s3_items,
                           s4_items=s4_items,
                           dashboard_generated_time_iso=dashboard_generated_time_iso,
                           auto_refresh_ms=AUTO_REFRESH_INTERVAL_SECONDS * 1000,
                           ticket_base_url=ticket_base_url,
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


@app.route('/display')
@limiter.exempt
def display_default():
    """Public display redirect (no authentication required for TV displays)."""
    return redirect(f'/display/{DEFAULT_VIEW_SLUG}')


@app.route('/display/<view_slug>')
@limiter.exempt
def display_public(view_slug):
    """Public display route for TV screens (no authentication required)."""
    if view_slug not in SUPPORTED_VIEWS:
        abort(404, description=f"Unsupported view: {view_slug}")

    agent_id = request.args.get('agent_id', type=int)
    current_view_display = SUPPORTED_VIEWS[view_slug]

    app.logger.info(f"Loading PUBLIC display for view: {current_view_display} (slug: {view_slug})")

    s1_items, s2_items, s3_items, s4_items, last_sync_time = get_tickets_for_view(view_slug, agent_id=agent_id)

    # Use last_sync_time from Codex if available, otherwise use current time
    if last_sync_time:
        dashboard_generated_time_iso = last_sync_time
    else:
        generated_time_utc = datetime.datetime.now(datetime.timezone.utc)
        dashboard_generated_time_iso = generated_time_utc.isoformat()

    section1_name = f"Open {current_view_display} Tickets"
    section2_name = "Customer Replied"
    section3_name = "Needs Agent / Update Overdue"
    section4_name = f"Other Active {current_view_display} Tickets"

    # Get PSA ticket base URL for ticket links
    ticket_base_url = get_psa_ticket_base_url()

    return render_template(INDEX_TEMPLATE,
                           s1_items=s1_items,
                           s2_items=s2_items,
                           s3_items=s3_items,
                           s4_items=s4_items,
                           dashboard_generated_time_iso=dashboard_generated_time_iso,
                           auto_refresh_ms=AUTO_REFRESH_INTERVAL_SECONDS * 1000,
                           ticket_base_url=ticket_base_url,
                           current_view_slug=view_slug,  # Keep original slug for API calls
                           current_view_display=current_view_display,
                           supported_views=SUPPORTED_VIEWS,
                           page_title_display=f"{current_view_display} (TV Display)",
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

    s1_items, s2_items, s3_items, s4_items, last_sync_time = get_tickets_for_view(view_slug, agent_id=agent_id)

    # Use last_sync_time from Codex if available, otherwise use current time
    if last_sync_time:
        dashboard_time_iso = last_sync_time
    else:
        dashboard_time_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    response_data = {
        's1_items': s1_items,
        's2_items': s2_items,
        's3_items': s3_items,
        's4_items': s4_items,
        'total_active_items': len(s1_items) + len(s2_items) + len(s3_items) + len(s4_items),
        'dashboard_generated_time_iso': dashboard_time_iso,
        'view': current_view_display,
        'section1_name_js': f"Open {current_view_display} Tickets",
        'section2_name_js': "Customer Replied",
        'section3_name_js': "Needs Agent / Update Overdue",
        'section4_name_js': f"Other Active {current_view_display} Tickets"
    }

    app.logger.debug(f"API: Returning {response_data['total_active_items']} total items")
    return jsonify(response_data)


# ====================  Health Check ====================

@app.route('/health', methods=['GET'])
@limiter.exempt
def health_check():
    """
    Comprehensive health check endpoint.

    Checks:
    - Disk space
    - Core service availability
    - Codex service availability (for ticket data)

    Returns:
        JSON: Detailed health status with HTTP 200 (healthy) or 503 (unhealthy/degraded)
    """
    # Initialize health checker
    health_checker = HealthChecker(
        service_name='beacon',
        dependencies=[
            ('core', 'http://localhost:5000'),
            ('codex', 'http://localhost:5010')
        ]
    )

    return health_checker.get_health()


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

    app.run(host='127.0.0.1', port=5001, debug=False)
