# HiveMatrix Beacon

Real-time ticket dashboard for monitoring helpdesk and professional services.

## Overview

Beacon provides a visual monitoring tool for support teams to track ticket status at a glance. It displays tickets from PSA systems (via Codex) in prioritized categories with SLA indicators.

**Port:** 5001

## Features

- **Real-Time Updates** - Auto-refreshes every 30 seconds
- **Categorized Views** - Open, customer replied, overdue, other active
- **Dual Dashboards** - Helpdesk and Professional Services views
- **SLA Indicators** - Visual status for overdue/critical/warning
- **Priority Highlighting** - Color-coded priority levels
- **Agent Filtering** - Filter tickets by assigned agent

## Tech Stack

- Flask + Gunicorn
- No database (uses Codex API)

## Key Endpoints

- `GET /helpdesk` - Helpdesk ticket dashboard
- `GET /professional-services` - Professional services dashboard
- `GET /api/tickets/<view>` - Get tickets for auto-refresh

## Ticket Categories

1. **Open** - Requires first response
2. **Customer Replied** - Needs agent attention
3. **Needs Agent / Overdue** - SLA breached or critical
4. **Other Active** - On hold, waiting, pending

## Environment Variables

- `CORE_SERVICE_URL` - Core service URL
- `CODEX_SERVICE_URL` - Codex service URL

## Dependencies

Beacon requires:
- **Core** - For service-to-service authentication
- **Codex** - For ticket data from PSA systems

## Documentation

For complete installation, configuration, and architecture documentation:

**[HiveMatrix Documentation](https://skelhammer.github.io/hivematrix-docs/)**

## License

MIT License - See LICENSE file
