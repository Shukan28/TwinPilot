# TwinPilot — Self-Experimenting Digital Twin

An advanced AI Cockpit dashboard prototype for real-time monitoring and autonomous optimization of vehicle assembly line operations. TwinPilot represents a self-experimenting digital twin system that combines real-time diagnostics, predictive analytics, and trustworthy AI insights.

**Accenture PS Prototype | Hackathon Project**

---

## 🎯 Overview

TwinPilot is an intelligent manufacturing dashboard that provides:

- **Real-Time Monitoring**: Live telemetry from 9 manufacturing stations (Stamping, Welding, Underbody, Painting, Powertrain, Doors, Interior, Electronics, Final Inspection)
- **Predictive Analytics**: AI-driven anomaly detection and trend forecasting
- **Autonomous Optimization**: System recommendations for stress mitigation and throughput improvement
- **Trustworthy AI**: Transparent decision logging, audit trails, and responsible AI frameworks
- **Multi-Page Cockpit Interface**: Seamless navigation between real-time dashboards, analytics, and trust/compliance views

---

## 🚀 Features

### Core Dashboard (Cockpit)
- Live monitoring of station cycle times and health metrics
- Interactive scenario modeling (Scenarios A, B, C)
- Stress detection and autonomous resolution
- Real-time chat bot for operator assistance
- Trust score tracking and anomaly visualization

### Diagnostics & Analytics
- Detailed performance metrics by station
- Historical data analysis
- Anomaly trend charts
- Predictive forecasting visualizations

### Trust & Responsible AI
- AI decision audit logs
- Operator override tracking
- System integrity indicators
- Compliance & safety metrics

### Enhanced UX
- High-fidelity UI with responsive design
- Web Audio synth for system notifications
- Interactive controls and real-time updates
- Multi-page state synchronization via localStorage

---

## 📁 Project Structure

```
TwinPilot/
├── index.html              # Concept/hero landing page
├── dashboard.html          # Main AI Cockpit dashboard
├── analytics.html          # Diagnostics and analytics views
├── responsible-ai.html     # Trust Center & compliance dashboard
├── app.js                  # Core application logic & state management
├── style.css               # Unified styling across all pages
└── README.md               # This file
```

### Key Components

| File | Purpose |
|------|---------|
| `app.js` | Central state management, audio synthesis, localStorage sync |
| `style.css` | Responsive design with CSS variables for theming |
| `dashboard.html` | Real-time operations cockpit with scenario modeling |
| `analytics.html` | Performance analytics and diagnostic tools |
| `responsible-ai.html` | AI transparency, audit logs, and trust metrics |

---

## 🛠️ Tech Stack

- **Frontend**: HTML5, CSS3, Vanilla JavaScript (ES6+)
- **State Management**: localStorage-based client-side persistence
- **UI Components**: Lucide Icons library
- **Audio**: Web Audio API for system notifications
- **Architecture**: Multi-page SPA with shared navigation and state sync

---

## 📖 How to Use

### 1. **Running the Project**
   - Open `index.html` in a modern web browser (Chrome, Firefox, Edge, Safari)
   - Navigate between sections using the header navigation:
     - **Concept**: Project overview and hero section
     - **Cockpit**: Real-time operations dashboard
     - **Diagnostics**: Analytics and performance insights
     - **Trust Center**: Responsible AI audit and compliance

### 2. **Dashboard Controls**
   - **Play/Pause**: Toggle live data updates
   - **Scenario Selection**: Choose scenarios (A, B, C) to model different operating conditions
   - **Stress Mode**: Trigger stress scenarios and observe autonomous mitigation
   - **Chat**: Interact with TwinPilot AI for real-time assistance

### 3. **State Persistence**
   - Application state is automatically saved to browser localStorage
   - State persists across page navigations and browser sessions
   - Reload or switch pages to see synchronized updates

---

## 🔧 Configuration

### Key Parameters (in `app.js`)

- **Station Configurations**: Customize station names and base cycle times
- **Default State**: Adjust initial trust scores, health metrics, and thresholds
- **Audio Notifications**: Modify sound types (beep, alert, critical, chime)

### Customization Examples

```javascript
// Modify station configs
const stations = {
  S1: { name: 'Stamping', baseCycle: 42.1 },
  // ... adjust cycle times or add/remove stations
};

// Adjust default metrics
const defaultState = {
  trustScore: 94,        // AI trust percentage
  overallHealth: 98.4,   // Factory health %
  throughput: 42.2,      // Units/hour
};
```

---

## 📊 Dashboard Metrics Explained

| Metric | Meaning |
|--------|---------|
| **Trust Score** | Confidence level in AI recommendations (0-100%) |
| **Overall Health** | Aggregate manufacturing system status |
| **Throughput** | Production units per hour |
| **Cycle Time** | Time per production cycle at each station |
| **Anomaly Status** | Detection of deviations from baseline patterns |
| **Stress Level** | System load and risk indicators |

---

## 🔐 Responsible AI Features

- **Audit Logging**: Every system decision is logged with timestamp and operator ID
- **Override Tracking**: Records when operators reject AI recommendations
- **Transparency**: Full visibility into AI reasoning and confidence scores
- **Safety Compliance**: Built-in constraints for operator safety and regulatory adherence

---

## 🎨 Theming & Customization

The application uses CSS custom properties for easy theming:

```css
--primary-bg: #0f1419;           /* Dark background */
--accent-healthy: #4ade80;       /* Green for healthy metrics */
--accent-warning: #fbbf24;       /* Yellow for warnings */
--accent-critical: #ef4444;      /* Red for critical alerts */
```

Modify these in `style.css` to change the entire UI appearance.

---

## 📱 Browser Support

- Chrome/Chromium (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)

*Note: Web Audio API support required for notification sounds*

---

## 👥 Team & Attribution

- **Developed by**: Accenture PS
- **Prototype**: Hackathon Project
- **UI Icons**: Lucide Icons
- **Fonts & Libraries**: Industry-standard open web technologies

---

## 📝 License

This is a prototype project for demonstration and evaluation purposes.

---

## 🚀 Future Enhancements

- [ ] Backend API integration for real production data
- [ ] Machine learning model pipeline for advanced predictions
- [ ] Mobile app companion (React Native/Flutter)
- [ ] Real-time data export (CSV, PDF)
- [ ] Advanced user role management (Admin, Operator, Analyst)
- [ ] WebSocket support for live multi-user collaboration
- [ ] Integration with IoT sensor networks

---

## 📞 Support & Feedback

For questions, issues, or feedback about TwinPilot, please reach out to the development team.
