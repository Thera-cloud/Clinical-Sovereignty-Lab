# Coach Portal UX Audit — Master Coach Perspective
**Date:** March 4, 2026  
**Test Account:** audit_mastercoach  
**Password:** AuditTest2026!  
**URL:** https://coach.sovereignsanctuary.net

---

## Pre-Login Checklist

### Landing Page
- [ ] Page loads without errors
- [ ] SSL certificate is valid (HTTPS)
- [ ] Login form is visible and properly styled
- [ ] "Coach" branding is clear
- [ ] No client/admin options visible (portal separation)

### Login Flow
- [ ] Username field accepts input
- [ ] Password field masks input
- [ ] Login button responds to click
- [ ] WebSocket connection establishes (check browser console for "connected")
- [ ] No stuck loading states
- [ ] Proper error handling for wrong credentials

### Post-Login Navigation
- [ ] If consent screen appears → accept and verify navigation continues
- [ ] If ethics agreement appears → accept and verify navigation continues
- [ ] Successfully enters Coach Dashboard (not redirected to login or client portal)

---

## Tab 1: CLIENTS

### Client List Display
- [ ] **Client visibility:** Can you see clients?
  - Expected: Audit Student 1 should appear (assigned to assistant Audit Lawyer 1)
  - Note total client count displayed
- [ ] **Information shown per client:**
  - [ ] Name
  - [ ] Profile picture/avatar
  - [ ] Coach assignment
  - [ ] Tier/subscription level
  - [ ] Last session date
  - [ ] Risk level or status indicator
  - [ ] Family/company grouping (if applicable)

### Filter Options
- [ ] **"All" filter** — Shows all clients (grouped by family/company, individuals separate)
- [ ] **"Clients" filter** — Shows every client as individual row (no family grouping)
- [ ] **"Families" filter** — Only shows clients with family_id, grouped by family
- [ ] **"Coach-Only" filter** — Only shows COACH_ONLY tier clients
- [ ] **"Company" filter** — Only shows clients with company_id, grouped by company
- [ ] Filter buttons are clearly labeled and responsive
- [ ] Active filter is visually distinct
- [ ] Client list updates immediately when filter changes

### Client Detail View
- [ ] Click on a client opens detail view
- [ ] Detail view shows:
  - [ ] Full profile information
  - [ ] Session history
  - [ ] Notes/comments
  - [ ] Risk assessment
  - [ ] Contact information
  - [ ] Family/company association
- [ ] Navigation back to list works
- [ ] No overlapping text or broken layout

### UX Quality
- [ ] Loading states are clear (spinner or skeleton)
- [ ] Empty states have helpful messaging
- [ ] Search/filter functionality is intuitive
- [ ] Client cards/rows have consistent styling
- [ ] Responsive design works on different screen sizes

**Rating (1-10):** _____  
**What works well:**  
**What's broken/missing:**  
**UX issues:**  
**Screenshots:**

---

## Tab 2: SCHEDULE

### Calendar View
- [ ] Calendar renders properly
- [ ] Current date is highlighted
- [ ] Can navigate between months/weeks
- [ ] Existing sessions are displayed on calendar
- [ ] Sessions show time, client name, and type

### Create New Session
- [ ] "Create Session" or "Schedule" button is visible
- [ ] Click opens session creation form
- [ ] Form fields include:
  - [ ] Client selection (dropdown)
  - [ ] Date picker
  - [ ] Time slot selection
  - [ ] Duration options
  - [ ] Session type (Standard, DOJO, Consultation, etc.)
  - [ ] Notes field
- [ ] Client dropdown shows all assigned clients
- [ ] Time slots show availability (not double-booked)

### Available Time Slots
- [ ] Availability is clearly indicated
- [ ] Blocked/unavailable times are grayed out or hidden
- [ ] Time zone is displayed
- [ ] Slots are in reasonable increments (15/30/60 min)

### Schedule a Session for Client
- [ ] Select a client from dropdown
- [ ] Choose date and time
- [ ] Confirm session creation
- [ ] Session appears on calendar after creation
- [ ] Client receives notification (if applicable)

### Upcoming Sessions List
- [ ] List view shows upcoming sessions
- [ ] Sessions are sorted chronologically
- [ ] Each session shows: client, date/time, type, status
- [ ] Can click session for details
- [ ] Can cancel/reschedule from list

### UX Quality
- [ ] Calendar navigation is smooth
- [ ] No date picker bugs or timezone issues
- [ ] Session creation flow is intuitive (max 3-4 steps)
- [ ] Visual distinction between session types
- [ ] Mobile-friendly time picker

**Rating (1-10):** _____  
**What works well:**  
**What's broken/missing:**  
**UX issues:**  
**Screenshots:**

---

## Tab 3: INSIGHTS

### Metrics Display
- [ ] Dashboard shows key metrics at top:
  - [ ] Total clients
  - [ ] Active sessions this week/month
  - [ ] Average engagement score
  - [ ] Revenue/earnings summary
- [ ] Metrics have clear labels and units
- [ ] Values are up-to-date (not stale cached data)

### Client Risk Levels
- [ ] Risk assessment data is displayed
- [ ] Risk levels are color-coded (red=high, yellow=medium, green=low)
- [ ] List of at-risk clients is prominent
- [ ] Can click on at-risk client for more detail

### Engagement Data
- [ ] Shows client engagement metrics:
  - [ ] Session attendance rate
  - [ ] App login frequency
  - [ ] Response time to messages
  - [ ] Homework completion (if applicable)
- [ ] Data is per-client and aggregate
- [ ] Trends over time are visible (week/month/quarter)

### Charts & Graphs
- [ ] Charts render without errors
- [ ] Data visualizations are readable
- [ ] Legends and axis labels are clear
- [ ] Interactive hover states work (tooltips)
- [ ] No overlapping text or clipped content
- [ ] Charts resize properly on window resize

### Empty States & Loading
- [ ] If no data, helpful empty state message appears
- [ ] Loading spinners show when data is fetching
- [ ] No "undefined" or error text in UI
- [ ] Graceful handling of missing data points

### UX Quality
- [ ] Insights are actionable (not just vanity metrics)
- [ ] Visual hierarchy guides attention to important data
- [ ] Color scheme is consistent with platform design
- [ ] Can export or share insights (if applicable)

**Rating (1-10):** _____  
**What works well:**  
**What's broken/missing:**  
**UX issues:**  
**Screenshots:**

---

## Tab 4: BRIEFINGS

### Session Preparation Materials
- [ ] Briefings list shows upcoming sessions needing prep
- [ ] Each briefing includes:
  - [ ] Client name and photo
  - [ ] Session date/time
  - [ ] Session type (Standard, DOJO, etc.)
- [ ] Can click briefing to open full prep view

### Client History Summaries
- [ ] Shows previous session notes/summaries
- [ ] Displays key issues or themes from past sessions
- [ ] Recent messages or journal entries from client
- [ ] Risk factors or alerts highlighted
- [ ] Goals and progress notes visible

### Information Quality & Usefulness
- [ ] Summaries are concise and relevant (not too verbose)
- [ ] AI-generated insights are accurate
- [ ] Critical information is highlighted or bolded
- [ ] Information is organized logically (chronological or by topic)
- [ ] No duplicate or conflicting information

### UX Quality
- [ ] Easy to scan and digest quickly
- [ ] Can mark briefing as "reviewed"
- [ ] Can add pre-session notes
- [ ] Printing or PDF export works (if applicable)
- [ ] Search/filter briefings by client or date

**Rating (1-10):** _____  
**What works well:**  
**What's broken/missing:**  
**UX issues:**  
**Screenshots:**

---

## Tab 5: DOJO

### Dojo Tier Visibility
- [ ] All 7 dojo tiers are listed:
  1. [ ] **Therapist** — Clinical therapy scenarios
  2. [ ] **Theologian** — Faith-based counseling
  3. [ ] **Philosopher** — Existential/meaning-making
  4. [ ] **Judge** — Legal/ethical dilemmas
  5. [ ] **Hostile** — Adversarial client interactions
  6. [ ] **Crisis** — High-stakes emergency scenarios
  7. [ ] **Skeptic** — Resistant/doubtful clients
- [ ] Each tier shows description and difficulty level
- [ ] Coach's progress/score per tier is displayed

### Starting a Dojo Session
- [ ] "Start Session" or "Practice" button per tier
- [ ] Click opens dojo interface
- [ ] Session type selection (if applicable)
- [ ] Persona or scenario selection
- [ ] Can preview scenario before starting

### Dojo Interface Design
- [ ] Clear instructions on what to do
- [ ] Scenario text is readable and formatted well
- [ ] Input field for coach responses
- [ ] AI evaluation/feedback appears after each response
- [ ] Scoring rubric is visible or explained
- [ ] Can pause or exit session gracefully

### UX Quality
- [ ] Dojo flow feels like realistic practice (not gamified to absurdity)
- [ ] Feedback is constructive and specific
- [ ] Progress tracking motivates continued practice
- [ ] No overwhelming UI or information overload
- [ ] Mobile-friendly (if tested on smaller screen)

**Rating (1-10):** _____  
**What works well:**  
**What's broken/missing:**  
**UX issues:**  
**Screenshots:**

---

## Tab 6: CLASSROOM

### Video Upload — New Dropbox-Style UI
- [ ] Upload interface is visible and prominent
- [ ] Drag-and-drop zone is clearly indicated
- [ ] "Browse Files" button works
- [ ] Accepted file types are listed (MP4, MOV, etc.)
- [ ] File size limit is displayed
- [ ] Can select multiple files at once

### Upload Interface UX
- [ ] Upload progress bar shows during upload
- [ ] Can cancel upload before completion
- [ ] Success message appears after upload
- [ ] Error handling for unsupported formats or oversized files
- [ ] Uploaded videos appear in list immediately

### Content Management Features
- [ ] List of uploaded videos shows:
  - [ ] Thumbnail or preview
  - [ ] Video title
  - [ ] Upload date
  - [ ] Duration
  - [ ] View count (if applicable)
- [ ] Can edit video title/description
- [ ] Can delete videos
- [ ] Can organize videos into folders or categories

### UX Quality
- [ ] Upload flow is simple (ideally 1-2 clicks)
- [ ] Visual feedback at every step
- [ ] No confusing jargon or technical terms
- [ ] Works on slower internet connections (retries/resumable uploads)
- [ ] Preview/playback works inline without leaving page

**Rating (1-10):** _____  
**What works well:**  
**What's broken/missing:**  
**UX issues:**  
**Screenshots:**

---

## Tab 7: TRAINING

### Training/Mesh Session Features
- [ ] Training options are displayed:
  - [ ] Group training sessions
  - [ ] Peer coaching mesh
  - [ ] Master-assistant training
- [ ] Can join or create training sessions
- [ ] Shows scheduled training sessions
- [ ] Can view past training history

### Quiz or Evaluation Options
- [ ] Quiz or assessment tools are available
- [ ] Can take self-assessments
- [ ] Can assign quizzes to assistant coaches (if applicable)
- [ ] Quiz results are displayed with feedback
- [ ] Scoring rubrics are transparent

### What's Available
- [ ] Training materials or curriculum visible
- [ ] Progress tracking per training module
- [ ] Certificates or badges (if applicable)
- [ ] Recommended training based on role/tier

### UX Quality
- [ ] Training feels purposeful (not busywork)
- [ ] Clear connection between training and real coaching scenarios
- [ ] Navigation between modules is intuitive
- [ ] Can resume incomplete training
- [ ] Mobile-friendly for on-the-go learning

**Rating (1-10):** _____  
**What works well:**  
**What's broken/missing:**  
**UX issues:**  
**Screenshots:**

---

## Tab 8: FINANCIALS

### Earnings Display
- [ ] Total earnings shown prominently
- [ ] Breakdown by period (week/month/year)
- [ ] Earnings trend chart visible
- [ ] Earnings per session type (Standard, DOJO, Consultation)

### Session Billing Information
- [ ] List of billable sessions
- [ ] Payment status per session (Paid, Pending, Waived)
- [ ] Client payment details (if applicable)
- [ ] Can filter by date range or payment status

### QuickBooks Integration Options
- [ ] "Connect to QuickBooks" button visible (if not connected)
- [ ] If connected, shows sync status
- [ ] Can disconnect/reconnect QuickBooks
- [ ] Sync logs or history visible
- [ ] Error handling for failed syncs

### UX Quality
- [ ] Financial data is accurate and up-to-date
- [ ] No confusing accounting jargon
- [ ] Can export financial reports (CSV, PDF)
- [ ] Tax-related information is clear (1099 preview, etc.)
- [ ] Privacy/security messaging for financial data

**Rating (1-10):** _____  
**What works well:**  
**What's broken/missing:**  
**UX issues:**  
**Screenshots:**

---

## Tab 9: FOLDER

### Document Storage
- [ ] Folder/file tree is displayed
- [ ] Can create new folders
- [ ] Can upload documents (PDF, DOCX, etc.)
- [ ] File size and type limits are clear

### Client Files
- [ ] Can filter files by client
- [ ] Client files are organized clearly (per-client folders or tags)
- [ ] Can view/download files
- [ ] File preview works inline (for PDFs, images)

### File Management Interface
- [ ] Can rename, move, delete files
- [ ] Can share files with clients (if applicable)
- [ ] Search functionality works
- [ ] Sorting options (name, date, size)
- [ ] Storage quota or usage is displayed

### UX Quality
- [ ] File manager feels familiar (like Dropbox/Google Drive)
- [ ] Drag-and-drop for organization
- [ ] Batch operations (select multiple, delete all)
- [ ] Responsive on mobile (or states "desktop only" clearly)
- [ ] No data loss on accidental deletes (trash/recycle bin)

**Rating (1-10):** _____  
**What works well:**  
**What's broken/missing:**  
**UX issues:**  
**Screenshots:**

---

## Tab 10: ASSISTANTS

### Assistant Coach Display
- [ ] **Audit Lawyer 1 appears** as an assistant coach
- [ ] Each assistant shows:
  - [ ] Name and profile picture
  - [ ] Role (Assistant Coach)
  - [ ] Supervised hours logged
  - [ ] Active clients assigned

### Hierarchy Management Features
- [ ] Can view master-assistant relationships
- [ ] Hierarchy tree or diagram is clear
- [ ] Can add new assistant (if applicable)
- [ ] Can remove assistant (with confirmation)

### Supervised Hours Tracking
- [ ] Total supervised hours for each assistant
- [ ] Recent sessions logged for supervision
- [ ] Can attest/approve hours
- [ ] Attestation status is clear (Pending, Approved)
- [ ] History of attested hours visible

### Assistant Management Actions
- [ ] Can view assistant's client list
- [ ] Can assign clients to assistant
- [ ] Can message/communicate with assistant
- [ ] Can review assistant's session notes (if applicable)
- [ ] **DO NOT TEST:** Deleting or modifying relationships (as instructed)

### UX Quality
- [ ] Hierarchy is easy to understand at a glance
- [ ] Actions are clearly labeled (no ambiguous icons)
- [ ] Confirmation dialogs prevent accidental changes
- [ ] Mobile-friendly (if tested on smaller screen)
- [ ] Help text or tooltips for complex features

**Rating (1-10):** _____  
**What works well:**  
**What's broken/missing:**  
**UX issues:**  
**Screenshots:**

---

## Overall UX Assessment

### Navigation Quality Between Tabs
- [ ] Tab bar is always visible (sticky header or sidebar)
- [ ] Active tab is clearly highlighted
- [ ] Tab labels are descriptive (not cryptic icons only)
- [ ] Keyboard navigation works (Tab key, arrow keys)
- [ ] No accidental tab switches (stable UI)

### Loading Times
- [ ] Initial portal load time: _____ seconds
- [ ] Tab switch time: _____ seconds (average)
- [ ] Client list load time: _____ seconds
- [ ] Calendar render time: _____ seconds
- [ ] No tabs take >5 seconds to load (without network issues)

### Broken Elements, Overlapping Text, Missing Data
- [ ] No 404 errors on any tab
- [ ] No "undefined" or "[object Object]" in UI
- [ ] No overlapping text or clipped content
- [ ] No missing profile pictures (default avatars are fine)
- [ ] No blank sections that should have content

### Responsiveness
- [ ] Portal works on desktop (tested resolution: _____)
- [ ] Portal works on tablet (if tested: _____)
- [ ] Portal works on mobile (if tested: _____)
- [ ] Zoom in/out doesn't break layout (test Cmd/Ctrl + plus/minus)
- [ ] Side-by-side windows work (test half-screen width)

### Visual Design Consistency
- [ ] Colors match design system (gold, cyan, purple)
- [ ] Typography is consistent across tabs
- [ ] Button styles are uniform
- [ ] Spacing and padding are consistent
- [ ] Dark theme is cohesive (background, cards, text)

### Critical Bugs Found
1. _______________________________________________________________
2. _______________________________________________________________
3. _______________________________________________________________

### Top 5 UX Improvements Needed
1. _______________________________________________________________
2. _______________________________________________________________
3. _______________________________________________________________
4. _______________________________________________________________
5. _______________________________________________________________

### Top 3 Things That Work Well
1. _______________________________________________________________
2. _______________________________________________________________
3. _______________________________________________________________

---

## Final Overall Portal Rating (1-10): _____

**Reasoning:**

---

## Recommendations for Immediate Action
- [ ] _______________________________________________________________
- [ ] _______________________________________________________________
- [ ] _______________________________________________________________

## Recommendations for Next Sprint
- [ ] _______________________________________________________________
- [ ] _______________________________________________________________
- [ ] _______________________________________________________________

---

**Auditor Notes:**
(Space for additional observations, edge cases, or surprising findings)
