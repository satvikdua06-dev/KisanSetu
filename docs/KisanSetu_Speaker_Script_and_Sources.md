# KisanSetu: speaker script and sources

Tech4Bharat 2026, Challenge 6.1. Target delivery: 6 to 8 minutes (about 35 seconds per slide). The same notes are embedded in the deck.

## Slide 1: KisanSetu (title)

**Main message.** KisanSetu is a selling network for farmers, not another price-lookup app.

**Say.** Good morning. We are presenting KisanSetu, our response to Challenge 6.1: farmers sell at the wrong time, place and price. Setu means bridge. KisanSetu is a bridge between a farmer's harvest and a better market. It is a network of coordinated AI agents that helps a farmer find, weigh up and carry out a better sale, and the farmer makes every decision.

**Transition.** To see why that matters, look at what selling actually involves for a small farmer.

## Slide 2: Growing the produce is only half the challenge. Getting a fair return is the other half

**Main message.** The problem is systemic: six linked constraints, not one missing piece of price information.

**Say.** A small farmer faces six problems at once. They cannot easily see net prices across markets. Their quantity is too small to interest large buyers. They depend on a few local buyers. A better price elsewhere can disappear once transport is paid. Perishable produce forces a quick sale. And the transaction itself can bring disputes over quantity, deductions and payment. These are linked. Knowing that another mandi pays more does not help if you cannot afford the truck or find a buyer there.

**Transition.** So if the problems are connected, do today's tools treat them as connected?

## Slide 3: Farmers have access to information. What they need is coordinated action

**Main message.** Our differentiation is coordination across the selling journey, not any single feature.

**Say.** Price boards, buyer listings and transport directories already exist, and we are not claiming otherwise. The gap is that each one stops at information and leaves the farmer to join the dots. KisanSetu takes each of those services one step further and links them in a single workflow: net realisation instead of quoted price, matched demand instead of a list, collective selling instead of individual advice.

**Transition.** Here is what that connected workflow looks like as a product.

**Technical clarification.** We do not claim that no existing platform offers any of these services. The claim is narrower: one shared agentic workflow that coordinates them.

## Slide 4: One intelligent network. From anticipated harvest to completed sale

**Main message.** KisanSetu is one workflow with eight connected services, and the farmer sits at the centre of it.

**Say.** A farmer tells KisanSetu four things, by voice, in their own language: what they are growing, how much, when it will be ready and where they are. From there the platform works through market intelligence, buyer matching, collective selling, logistics, storage choices and the transaction record. These are not eight apps. They are eight steps that share one view of the same harvest.

**Transition.** What turns eight services into one workflow is the agent layer.

**Technical clarification.** Everything on this slide is proposed capability for the prototype, not a description of a live system.

## Slide 5: Not another chatbot. A network of agents that plans, coordinates and acts

**Main message.** Seven specialised agents work through one orchestrator and one shared state, with people approving anything consequential.

**Say.** This is the core of the system. The orchestrator takes the farmer's goal, keeps the state of the selling workflow, hands tasks to seven specialised agents, checks what comes back and decides the next step. If the Buyer Matching Agent finds an order larger than the farmer can fill, the orchestrator asks the Collective Selling Agent to find the rest, then the Logistics Agent to price the delivery. That hand-off is what makes this agentic. Before any commitment, a person approves.

**Transition.** Let us follow one harvest through those agents.

**Technical clarification.** Not everything is an LLM. Arithmetic, cost estimation, matching constraints, aggregation and optimisation are deterministic code. The LLM handles intent, planning, tool selection, coordination, exceptions and conversation.

## Slide 6: One farmer. One harvest. A coordinated selling journey

**Main message.** Eight steps, five agents and one approval point take a harvest from registration to reconciled payment.

**Say.** Take a farmer in Gujarat expecting three thousand kilos of tomatoes in five days. She registers the harvest by voice. The Market Intelligence Agent compares nearby markets on net realisation. The Buyer Matching Agent finds a food processor that needs five thousand kilos in that window, which is more than she has. So the Collective Selling Agent looks for nearby farmers or an FPO to supply the other two thousand. The Logistics Agent plans one vehicle across the pickups. The orchestrator puts price, deductions, transport and expected proceeds into a single proposal. Nothing moves until each farmer approves their own share. Then dispatch, delivered quantities and payment are tracked.

**Transition.** The step that changes the farmer's decision is the second one, so let us look at the numbers behind it.

**Technical clarification.** This scenario is illustrative, not a completed transaction. In the prototype, every buyer demand or offer will be labelled as real, sourced or simulated.

## Slide 7: We optimise for what farmers actually earn, not just the price displayed on a screen

**Main message.** The highest quoted price is not necessarily the highest earning. We rank on expected net realisation.

**Say.** These are illustrative figures. The local mandi quotes twenty rupees a kilo, the regional mandi twenty-four and a distant wholesale market twenty-seven. Most tools would point to twenty-seven. After transport and other costs the picture changes: nineteen, twenty-one and twenty-one. On a thousand kilos the distant market earns exactly the same as the regional one, with a longer trip and more risk for a perishable crop. KisanSetu ranks options by expected net, shows the assumptions, and then asks the agents whether pooling, a direct buyer or shared transport can improve the best option.

**Transition.** The farmer is at the centre, but she is not the only one who gains.

**Technical clarification.** All figures are illustrative. Net = quoted price minus transport and other costs: 20-1=19, 24-3=21, 27-6=21. Real comparisons will only include cost components for which data is available, and will show source, timestamp and uncertainty.

## Slide 8: Empowering farmers while connecting the entire agricultural value chain

**Main message.** Every participant gets something useful, which is what gives each of them a reason to join the network.

**Say.** A market-access network only works if every side has a reason to take part. Farmers get intelligence, buyers and bargaining power. FPOs get a tool to aggregate and coordinate their members. Buyers and processors get reliable supply matched to their requirements. Transporters get fuller vehicles. Storage operators see demand coming. Institutions get visibility into market access. KisanSetu sits in the middle moving four things: supply, demand, transport capacity and information.

**Transition.** Now the question a technical judge will ask: how is this actually built?

**Technical clarification.** These are intended roles. We are not claiming any signed-up buyers, transporters, FPOs or institutional partners.

## Slide 9: A coordinated agentic architecture built around shared state, reliable data and human control

**Main message.** Five layers, with the model doing only what needs a model, data coming from outside systems, and people approving commitments.

**Say.** This is the proposed build. At the top, role-specific interfaces, voice-first for farmers. Below that, ordinary backend services in FastAPI. In the middle, the orchestrator and seven agents, which talk through defined tools and a shared operational state rather than free-form chat. Layer four separates the two kinds of intelligence: green is the language model, white is conventional algorithms. At the bottom, PostgreSQL holds the operational record and a persistent memory of orders, decisions and approvals. On the right, two things sit deliberately outside the agents: external data sources, and human approval gates.

**Transition.** With the build credible, what should it change for farmers?

**Technical clarification.** This is a proposed architecture, not a statement that all components are operational. External integrations will be live where an API is supported and clearly labelled simulations otherwise. Market data does not originate from the LLM.

## Slide 10: Better market access can translate into stronger farmer economics

**Main message.** We are stating intended outcomes and how we will measure them, not claiming results.

**Say.** We want to be precise here. We have no results to report yet, so we will not quote percentages. What we have is five intended outcomes and seven metrics that would tell us whether they are happening. The headline metric is change in net realisation per kilogram, because that is money in the farmer's hand. The others track reach, collective volume, transport cost, completion, payment speed and whether farmers come back.

**Transition.** Impact only lasts if the platform can pay for itself.

**Technical clarification.** All metrics are targets for future evaluation. A fair evaluation would compare participating farmers with a comparable baseline for the same crop and season.

## Slide 11: A farmer-first platform with multiple institutional revenue opportunities

**Main message.** Institutions that gain from coordinated supply pay. Small farmers do not pay to reach their own market.

**Say.** Revenue comes from the organisations that benefit from reliable, aggregated supply: FPOs and cooperatives, buyers and processors, logistics providers, livelihood programmes and public institutions. For the individual small farmer, essential market intelligence and basic selling help stay free or very low cost. We scale carefully: one crop in one region, validated with farmers and an FPO, before adding buyers, transporters, crops and neighbouring markets.

**Transition.** Let us close with where this leads.

**Technical clarification.** These are potential revenue streams, not signed contracts. Any government deployment is subject to procurement and integration requirements, and we are not claiming any such arrangement.

## Slide 12: From fragmented agricultural supply to intelligent market access

**Main message.** KisanSetu turns fragmented selling into a coordinated, farmer-controlled process.

**Say.** A farmer already does the hard part, which is growing the crop. Selling it well should not depend on luck, on who you happen to know, or on how much you happen to grow. KisanSetu gives a small farmer the intelligence, the buyers, the bargaining power and the coordination that large suppliers take for granted, and leaves the decision with the farmer. Thank you. We would be glad to take your questions.

**Transition.** Open for questions. Likely ones: data sources for prices, what is real versus simulated in the prototype, and how approvals work.

Spoken word count: about 927 words.

## Sources

**External data.** None. No market data, statistics or impact figures from outside sources are used. The tomato scenario (slide 6) and the price and cost figures (slide 7) are illustrative values from the project brief and are labelled as such on the slides.

**Images.** No photographs are used. All diagrams are native, editable PowerPoint shapes and one native chart.

**Icons.** Font Awesome Free 5 (via the react-icons package), licensed CC BY 4.0, https://fontawesome.com. Embedded as PNG.

**Fonts.** Arial (headings) and Calibri (body), both shipped with Microsoft Office.
