📘 DSSG Volunteer Impact Dashboard – Refined PRD (V1)  
1\. Overview  
Objective  
Build an internal-facing Streamlit dashboard to track and visualize DSSG’s volunteer growth, event participation, and estimated impact.  
This dashboard will:

* Use existing Google Sheet data (2 tabs)

* Require minimal manual updates

* Be easy to hand off and maintain

* Support future open-sourcing

---

2\. Data Sources  
All data comes from a single Google Sheet with two tabs:  
Tab 1: Volunteer List  
Fields include:

* Volunteer email (unique identifier)

* Name

* Registration date

* Domain of expertise

* Years of experience

* Industry

* Tools

* Other background fields

Purpose:

* Total volunteer count

* Monthly growth

* Volunteer background distributions

---

Tab 2: Eventbrite Participants  
Contains all Eventbrite exports (meetups \+ hackathons).  
Fields include:

* Event name

* Event start date

* Attendee email

* Attendee status

* Order/ticket metadata

Events are distinguished by event name:

* “Meetup” \= monthly event

* Hackathons \= specific named events (2 so far)

Purpose:

* Total events

* Total participants

* Attendance trend over time

* Hackathon vs meetup split

* Estimated volunteer hours

* Estimated dollar impact

---

3\. Business Logic  
3.1 Event Classification  
Event type is derived from event name:

* If event\_name contains “Hackathon” → type \= “hackathon”

* Otherwise → type \= “meetup”

---

3.2 Volunteer Hours (Estimated)  
We do not log volunteer hours directly.  
For hackathons:

* Duration: 9am–6pm \= 9 hours

* Total hackathon hours \= (\# participants) × 9

For meetups:

* No hours counted in V1

---

3.3 Estimated Dollar Value  
For hackathons:  
Estimated Value \=  
(\# participants × 9 hours) × $50/hour  
Assumption:

* $50/hour equivalent tech consulting value

This number is used for impact storytelling.  
---

3.4 Active Volunteer (V1 Definition)  
We currently do not track volunteer hours.  
Define active volunteer as:  
Volunteer who attended at least one event (meetup or hackathon) in the last 90 days.  
---

4\. Core Metrics (V1)  
Top-Level KPIs

* Total Registered Volunteers

* Active Volunteers (last 90 days)

* Total Events

* Total Event Participants (cumulative)

* Total Hackathons

* Estimated Hackathon Volunteer Hours

* Estimated Dollar Impact

---

5\. Charts & Sections (Single Scroll Page)  
Section 1 – Overview KPIs  
Large metric cards.  
---

Section 2 – Volunteer Growth

* Line chart: Monthly new registrations

* Line chart: Cumulative volunteers over time

---

Section 3 – Event Participation

* Line chart: Monthly participants

* Bar chart: Participants per event

* Pie or bar: Meetup vs Hackathon breakdown

---

Section 4 – Impact

* Hackathon hours per event

* Total hackathon hours

* Estimated total dollar value

---

Section 5 – Volunteer Background  
From Volunteer List tab:

* Domain of expertise distribution

* Years of experience distribution

* Industry breakdown

* Tools distribution (top N)

---

6\. Architecture (V1 Simplicity)

* Streamlit frontend

* Direct read from Google Sheets CSV export OR public CSV link

* Pandas transformations in-app

* No database for V1

* No PII masking required (internal only)

Future V2:

* Add ETL layer

* Add database

* Add automation via Google Sheets API

---

7\. Non-Functional Requirements

* Easy to run locally

* No complex infra

* Clear data transformation functions

* Modular structure

* Logo displayed at top of dashboard

* Clean, minimal design

