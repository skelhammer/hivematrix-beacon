# Beacon - Ticket Dashboard

**Port**: 5001
**Database**: None (uses Codex API)
**Repository**: [hivematrix-beacon](https://github.com/skelhammer/hivematrix-beacon)

## Overview

Beacon is a real-time ticket dashboard for monitoring helpdesk and professional services tickets. It provides categorized views with SLA status indicators, priority highlighting, and agent filtering.

## Purpose

Beacon serves as a visual monitoring tool for support teams to track ticket status at a glance. It displays tickets pulled from Freshservice (via Codex) in prioritized categories to help teams identify urgent items quickly.

## Features

- **Real-Time Updates**: Auto-refreshes every 30 seconds
- **Categorized Views**:
  - Open tickets requiring response
  - Customer replied (needs attention)
  - Needs agent / update overdue
  - Other active tickets
- **Dual Dashboards**: Separate views for Helpdesk and Professional Services
- **SLA Indicators**: Visual status for overdue, critical, warning states
- **Priority Highlighting**: Color-coded priority levels
- **Agent Filtering**: Filter tickets by assigned agent
- **Ticket Links**: Click to open tickets directly in Freshservice

## Architecture

Beacon is a lightweight display service that:
- **Does NOT** store any data
- **Does NOT** connect to Freshservice directly
- Gets all data from Codex via authenticated API calls
- Uses service-to-service authentication through Core

```
Freshservice → Codex (sync) → Beacon (display)
```

## Key Endpoints

### Web Routes
- `/` - Redirects to default view (helpdesk)
- `/helpdesk` - Helpdesk ticket dashboard
- `/professional-services` - Professional services dashboard
- `/settings` - Beacon configuration

### API Endpoints
- `/api/tickets/<view_slug>` - Get tickets for auto-refresh

## Configuration

Beacon requires no manual configuration. It uses:
- `services.json` - Service registry (symlink from Helm)
- `.flaskenv` - Auto-generated environment variables

### Environment Variables
- `SERVICE_NAME` - Service identifier (beacon)
- `CORE_SERVICE_URL` - Core service URL for authentication

## Dependencies

Beacon depends on:
- **Core** - For service-to-service authentication tokens
- **Codex** - For ticket data via `/api/tickets/active` and `/api/freshservice/agents`

## Installation

Beacon is installed via Helm:

```bash
cd hivematrix-helm
source pyenv/bin/activate
python install_manager.py install beacon
```

Or manually:

```bash
cd hivematrix-beacon
./install.sh
```

## Running

### Via Helm
```bash
cd hivematrix-helm
python cli.py start beacon
```

### Manually
```bash
cd hivematrix-beacon
source pyenv/bin/activate
python run.py
```

Access at: `https://your-server/beacon/helpdesk`

## Usage

1. **Select View**: Use the tabs to switch between Helpdesk and [PLAN-G]
2. **Filter by Agent**: Use the dropdown to filter tickets by assigned agent
3. **Monitor SLA**: Watch color indicators for ticket urgency
4. **Click to Open**: Click ticket IDs to open in Freshservice

## Ticket Categories

### Section 1: Open Tickets
Tickets requiring first response or action:
- Status: Open
- No SLA violation yet

### Section 2: Customer Replied
Tickets where customer has responded:
- Needs agent attention
- May have SLA concerns

### Section 3: Needs Agent / Update Overdue
Critical tickets requiring immediate attention:
- SLA breached or critical
- Update overdue

### Section 4: Other Active
All other non-closed tickets:
- On hold
- Waiting on third party
- Pending status

## Troubleshooting

### No Tickets Displayed
1. Check Codex is running: `python cli.py status codex`
2. Verify ticket sync: Run `pull_freshservice.py` in Codex
3. Check logs: `python logs_cli.py beacon --tail 50`

### Agent Names Not Showing
1. Sync Freshservice agents: Run `pull_freshservice.py` in Codex
2. Verify agents synced: Check Codex `/api/freshservice/agents`

### Authentication Errors
1. Verify Core is running
2. Check `services.json` symlink exists
3. Ensure `CORE_SERVICE_URL` is set in `.flaskenv`

## Development

Beacon uses the standard HiveMatrix service pattern:
- ProxyFix middleware for proxy compatibility
- BEM CSS classes (no local stylesheets)
- Service-to-service authentication
- Nexus-injected navigation

## See Also

- [Services Overview](https://skelhammer.github.io/hivematrix-docs/services-overview/)
- [Codex Documentation](https://skelhammer.github.io/hivematrix-docs/services/codex/)
- [Architecture Guide](https://skelhammer.github.io/hivematrix-docs/ARCHITECTURE/)
