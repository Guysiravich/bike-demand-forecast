## 2. Actual, from billing filtered by tag

Azure Cost Management, ActualCost, 2026-10-01 to 2026-10-10, read on 2026-10-11 (USD; THB at
33.234). The monthly invoice email reads **USD 0** because this is an Azure for Students
subscription: usage is charged against the student credit, so nothing is due — the cost below
is what that credit paid.

| Scope | USD | THB | What it is |
|---|---|---|---|
| Resources tagged `lab=capstone` | **0.00** | **0** | both jobs, their environment, identities, log workspace, action group, alert rules, workbook |
| Shared base, `lab=1` | 1.65 | 55 | container registry (Basic, billed daily) and storage |
| Shared base, `lab=2` | 1.87 | 62 | tracking-server VM (0.14 of it compute), its public IP, disk, network |
| **Subscription total** | **3.52** | **117** | 0.336 USD (11.2 THB) a day on days with no cloud work |

By service: Container Registry 1.65 · Virtual Network (public IP) 1.21 · Storage 0.52 · Virtual
Machines 0.14 · everything else below 0.01.

## 3. The gap

**Fixed costs: estimate 11.3 THB a day, actual 11.2 — within 1%.** The registry (165 THB a month
estimated, 5.5 a day billed) and the VM's IP and disk were priced from the labs' own bills, which
is why they land.

**The project's own resources: estimated ~24 THB a month for hourly jobs, actual 0.** Two reasons,
both in our favour and both temporary: the jobs ran only during the drills and CD — about thirty
executions, not 24 a day — and every one of them fell inside the Container Apps monthly free
grant, as did Log Analytics' ingestion. Run hourly for a month, the jobs would use about 24,500
vCPU-seconds of the 180,000 free, so the bill for them would still be zero; the 24 THB in section
6 is the list-price value of that use, not a charge.

**The tracking server: estimated 317 THB a month at 24 hours a day, actual 0.14 USD (5 THB) in
October** — it ran a few hours on the deployment and drill days and is deallocated between
sessions. Left on for the demo week it would add about 10.5 THB a day; that, not the jobs, is the
cost to watch.

What the bill cannot show: the alert rules (about 0.10 USD each a month) bill at month end, so
they are not in a ten-day view yet.
