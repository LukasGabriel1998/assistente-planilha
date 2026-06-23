#!/usr/bin/env python3
"""Generate docs/stories/index.html with 48 expanded story synopses."""

from pathlib import Path

# Each story: (cn_title, en_subtitle, theme_tags, body_html)
STORIES = []

def story(cn, en, tags, body):
    STORIES.append((cn, en, tags, body.strip()))

# --- 1 Parenting (user reference style) ---
story(
    "女儿每天给母亲打三个电话",
    "When the Daughter Started Calling Her Mother Three Times a Day",
    "Relationship, parent-child dynamics, elder care, communication, family",
    """
<p>First-person narration alternates by chapter between <strong>Katie</strong> (daughter, 42, divorced after infidelity) and <strong>Katrina</strong> (mother, nearly 70, retired teacher). Katie has a college-age son and a teen daughter; she moved to her mother's coastal town for temporary work and calls three times a day. Katrina is capable and proud, but lonely—she sighs on the sofa when nobody is watching.</p>
<p>The novella is unusually explicit about <strong>phone-call scripts</strong> for adult children:</p>
<blockquote class="warning">
Do not jump in to solve every problem when you call.<br>
Do not fill silence with rambling while your mind is elsewhere—short sentences and real listening matter.<br>
Do not treat all their advice as outdated, or they will stop talking.<br>
Do not wait until a crisis to move back; by then many everyday things may already be too late.
</blockquote>
<h3>Healthy elder-parent behaviors modeled</h3>
<ul>
<li>Katrina keeps hobbies and friendships alive.</li>
<li>She uses smart-home gear without pretending to be helpless.</li>
<li>She writes down complex steps and keeps instructions visible.</li>
<li>She accepts help on her terms—not as bitter dependent, not as secretly drowning parent.</li>
</ul>
<p>A storm and power outage pressure the plot: remote monitoring fails, neighbors bring lanterns, and Katrina's calm protocols matter more than gadgets. The climax is quiet—a renegotiation of closeness, camera consent, data retention, and visit rhythm. Inheritance is reframed as living relationship, not only wills and property.</p>
<p><em>Genre:</em> contemporary family realism; alternating POV; didactic warmth (polarizing for some readers).</p>
""",
)

story(
    "当 AI 开始接管工厂后",
    "When AI Starts Running the Factory",
    "Near-future labor, algorithmic management, dignity, automation",
    """
<p><strong>Xu Bin</strong>, 38, was a senior fitter making precision appliance parts. After early retirement at 35 and six months unemployed, he returns as an "optimization specialist" on a smart line—ashamed among old colleagues, secretly proud until a younger coworker collapses and the algorithm flags his team as "low human-efficiency."</p>
<p>This is physical shop-floor fiction, not office satire: Xu Bin's muscle memory still matters for weird rejects and tool changes that no manual captures. Management speaks OEE and headcount; the company WeChat celebrates efficiency gains while two people per shift vanish from the roster.</p>
<h3>Pressure points</h3>
<ul>
<li>Overtime tied to algorithmic peaks vs family and school events.</li>
<li>Flat base pay + team KPI variable—helping a slower veteran costs him money.</li>
<li>Old masters see dashboards as betrayal; young hires treat humans as debug tools.</li>
</ul>
<p><strong>Lesson layer:</strong> survival requires collective transparency—shared metrics harm, documented tacit fixes, refusing heroics that hide systemic overload. Arc is not "learn to code" but negotiate visibility before the next headcount wave.</p>
<p><em>Genre:</em> near-future labor fiction; industrial melancholy; shop-floor solidarity.</p>
""",
)

story(
    "最后一份纸质情书",
    "The Last Paper Love Letter",
    "Memory media, craft, ritual, family archive",
    """
<p>First-person narrator, ~30, runs a small print shop—letterpress, envelopes, wax seals—against pure screen work. Her mother was a "paper romantic" who archived tickets and handwritten notes; the daughter believes feelings should live in <strong>tangible</strong> form. Margins are thin; wedding rush jobs keep the lights on.</p>
<p>The inciting fear: the last purely paper ritual might become a folder sync or dead link. Clients arrive with opposite anxieties—calligraphy before speech-to-text cheapens vows; grandparent letters must be copied before humidity wins.</p>
<h3>Object-as-plot</h3>
<p>Paper is slow memory: postage, drying ink, wrong addresses force intention. Digitization is temptation and threat—PDF proofs, influencer "aesthetic" letters that skip the waiting.</p>
<p><strong>Landing:</strong> qualified preservation—not paper forever, not all cloud—a scan exists, but one box stays physical; one letter still gets mailed because delay is the point.</p>
<p><em>Genre:</em> slice-of-life craft; memory media; gentle romance undertone.</p>
""",
)

story(
    "在直播间里重来的人生",
    "A Life Replay in the Livestream",
    "Time-loop, influencer economy, authenticity, gig identity",
    """
<p><strong>Lin Han</strong>, 32, failed actor turned emotional-anchor streamer—curated tears, gift-war peaks. Metrics replaced art; intimacy is transaction. "Rebirth" binds to <strong>broadcast performance</strong>: repeating the same slot, sponsor read, apology script.</p>
<p>Each loop tests micro-edits—truth vs performance, refusing toxic collabs, exiting guild contracts—while platform UI gives instant score feedback. Early loops optimize gifts and lose dignity; late loops accept smaller rooms and real speech.</p>
<h3>Cast pressure</h3>
<table>
<tr><th>Figure</th><th>Role</th></tr>
<tr><td>Guild / MC</td><td>Flow charts, penalties, artificial drama</td></tr>
<tr><td>Rival streamer</td><td>Mirror of cynicism</td></tr>
<tr><td>Family off-camera</td><td>Bills and expectations</td></tr>
<tr><td>Recordings of past self</td><td>Haunts via undeletable clips</td></tr>
</table>
<p><em>Genre:</em> time-loop; influencer dystopia; redemption with commercial realism.</p>
""",
)

story(
    "城市缝隙里的旧书摊",
    "The Used Book Stall in the City's Cracks",
    "Gentrification, neighborhood memory, informal culture",
    """
<p>First-person ~40, once a designer, lends floor space under stairs beside a shuttered print shop. The stall is a <strong>neighborhood archive</strong>—rescued inventory, regulars who barter gossip for titles, constant demolition notices.</p>
<h3>Ecosystem</h3>
<ul>
<li>Old bookseller — place memory.</li>
<li>Tenant activist — petitions vs inspections.</li>
<li>Developer liaison — polite displacement language.</li>
<li>Young café owners — ambivalent gentrifiers.</li>
<li>Municipal inspector — recurring cliff face.</li>
</ul>
<p>Plot rhythm: serial small erasures (power off, neighbor moves), punctuated by salvage wins. Central question: preserve objects, stories, or the habit of browsing?</p>
<p><em>Genre:</em> urban renewal realism; micro-portrait.</p>
""",
)

story(
    "他在异地执行的项目",
    "His Project in Another City",
    "Long-distance couple, logistics fatigue, ambiguous ending",
    """
<p>Alternating close third: <strong>Su Yuan</strong> (29, brand, city A) and <strong>Lu Chen</strong> (31, site PM, city B). Five years together; engagement low-key. Misunderstandings are <strong>structural</strong>—missed anniversaries from handover delays, unread voice notes during inspections, per-diem lifestyle vs her spreadsheet, "eighteen more months on site."</p>
<h3>Devices</h3>
<ul>
<li>Shared moving checklist — love as project management.</li>
<li>Delayed flights — hope/resentment cycles.</li>
<li>Return date slips — promise decay.</li>
</ul>
<p>Ending deliberately split: reunion with new terms, clean separation, or indefinite limbo. Value is recognizing when repair needs relocation, not only better messages.</p>
<p><em>Genre:</em> dual POV relationship realism; urban professionals.</p>
""",
)

story(
    "老小区的电梯战争",
    "The Elevator War in the Old Residential Compound",
    "Owner committee, common property, civic procedural drama",
    """
<p><strong>Old Zhang</strong>, ~65, retired state-enterprise engineer, 7-story walk-up (~1998, ~60 households). Government retrofit subsidy + mandatory poll turns every landing into a parliament of money and blame.</p>
<h3>Factions (each reasonable)</h3>
<ul>
<li>Pro-install seniors — knees, hospital runs.</li>
<li>Anti/delay bloc — assessments, maintenance distrust.</li>
<li>Investor landlords — vote tactics.</li>
<li>Property manager — liability shell game.</li>
</ul>
<p>Drama lives in quorum rules, proxy rumors, shaft placement, parking loss, cab width promises vs wheelchair reality. Trust networks form and fracture.</p>
<p><em>Genre:</em> neighborhood procedural; civic realism.</p>
""",
)

story(
    "她决定不再参加同学聚会",
    "She Decided to Stop Going to Class Reunions",
    "Social media performance, meritocracy hangover, boundaries",
    """
<p><strong>Yang Jing</strong>, ~35, outwardly fine—curated feeds, former class star. Reunion culture: WeChat hype, ranking subtext (car, kid's school, renovation photos).</p>
<p>Opt-out after cumulative micro-humiliations—oral-exam quizzing, comparison as concern, photos without consent. Triggers sanction narratives: ingrate, arrogant, "forgot roots."</p>
<p>Arc: quiet recalibration—grief for unequal community, reclaimed weekends, learning which two classmates matter without the banquet hall.</p>
<p><em>Genre:</em> first-person social fiction; essayistic interiority.</p>
""",
)

story(
    "当律师决定帮一个人撒谎",
    "When a Lawyer Decides to Help Someone Lie",
    "Legal ethics, procedural moral weight, uncomfortable endings",
    """
<p><strong>Cheng Wei</strong>, ~40, civil/commercial litigator, calm procedure. Clients entangled where formal truth and lived survival diverge; one asks for material misrepresentation "everyone does."</p>
<h3>Choice costs</h3>
<table>
<tr><th>Choice</th><th>Cost</th></tr>
<tr><td>Refuse lie</td><td>Client may lose house, visa, custody</td></tr>
<tr><td>Comply</td><td>Short win, license risk</td></tr>
<tr><td>Partial help</td><td>Both sides angry</td></tr>
<tr><td>Withdraw</td><td>Firm hostility</td></tr>
</table>
<p>Set in preparation rooms more than courtroom thunder. Endings stay ethically uncomfortable.</p>
<p><em>Genre:</em> legal ethics; anti-melodrama realism.</p>
""",
)

story(
    "最后一个会换屏的维修师傅",
    "The Last Repairman Who Still Knows How to Swap Screens",
    "Repair rights, skill extinction, mentor lineage",
    """
<p><strong>Master Tan</strong>, ~50s, module-level repair on a street of shifting facades—schematics, hot-air rework, donor boards. <strong>Apprentice Lin</strong> (~20s) wants speed; authorized shops push whole-unit swap; OS nags trade-in.</p>
<p>Repair is hidden infrastructure: a day of photos, contacts, small-business QR on cracked glass. Closure means skill extinction, not only unemployment.</p>
<p>Climax: corporate desk job documenting "unable to repair" vs training Lin on unprofitable board work because someone should still know.</p>
<p><em>Genre:</em> craft extinction; tech realism; gentle melancholy.</p>
""",
)

story(
    "我们在疫情后学会的事",
    "What We Learned After the Pandemic",
    "Ensemble aftermath, contradictory social lessons",
    """
<p>Multi-POV cycle (3–5 voices) 12–36 months after peak lockdown—delivery rider, clinic nurse, restaurant owner, remote returnee, teacher/student, optional elder refusing "back to normal."</p>
<p>Motifs: silent mutual-aid chats, QR muscle memory, revenge consumption vs empty savings, dating/divorce filings, career pivots. Chapters overlap one week so readers see the same street from incompatible angles.</p>
<p><strong>Claim:</strong> society stored contradictory lessons (save/spend, trust science/trust only self). Value is validation without one moral.</p>
<p><em>Genre:</em> post-crisis mosaic; ensemble portrait.</p>
""",
)

story(
    "当 AI 开始写公司财报",
    "When AI Starts Writing Corporate Earnings Reports",
    "Financial comms, linguistic normalization, fraud gradient",
    """
<p>Dual POV: disclosure specialist ~32 + board pressure at listed mid-cap. Models draft MD&amp;A tone and anomaly explanations; humans pick among drafts like choose-your-ending.</p>
<p>Triggers: missed quarter, inventory ambiguity, related-party murk. Teaches how <strong>approved template phrases</strong> smooth volatility until synonym shifts become fraud gradient—not one forged PDF.</p>
<p>Personal cost: 2 a.m. laptop, marriage strain, kid asking what parent does.</p>
<p><em>Genre:</em> financial thriller-lite; workplace ethics.</p>
""",
)

story(
    "异父异母的兄弟",
    "Stepbrothers Who Share No Blood",
    "Blended family, male affection, domestic politics",
    """
<p>Close third, boys ~17–22 and ~7–12, cohabiting after late remarriage—mismatched surnames, custody weekends, grandma allegiances. Older carries "model" burden; younger navigates playground "real dad" questions.</p>
<p>Inventory: fridge politics, red-packet amounts, homework/gaming rules, hospital seating, New Year rotation. Parents try hard and fail partially—not evil stepparent trope.</p>
<p>Arc: territorial silence → shared crisis → provisional brotherhood that may not survive college move-out.</p>
<p><em>Genre:</em> dual POV family realism.</p>
""",
)

story(
    "她在高铁上决定离婚",
    "She Decided to Divorce on the High-Speed Train",
    "Mobility, irrevocable choice, divorce logistics",
    """
<p><strong>Zhao Lin</strong>, ~34, on G-train business trip—seat class and duration as countdown. Marriage ~7 years; child 3–6 with grandparents; husband stable but absent or betrayal/financial lie/in-law siege.</p>
<p>Train as liminal tube: weak signal, landscapes like unstoppable life, drafts unsent. Parallel channels: husband logistics, friend/lawyer reality, parent guilt, kindergarten teacher as mundane anchor.</p>
<p>Ending palette: lawyer at terminus, scheduled confession, one more try, file after landing—small decisions not courthouse thunder.</p>
<p><em>Genre:</em> interior monologue; contemporary marriage.</p>
""",
)

story(
    "最后一个会手冲咖啡的保安",
    "The Last Security Guard Who Still Brews Pour-Over Coffee",
    "Invisible labor, night shift dignity, class at the lobby",
    """
<p><strong>Uncle Liu</strong>, ~58, night security at luxury tower, ex-factory or migrant pride. Pre-dawn pour-over—hand grinder, gifted single-origin—is anti-KPI existence measured by incident logs.</p>
<p>Orbit: delivery regular, insomniac tenant confessionals, property chief banning personal appliances, AI patrol app timing bathroom breaks.</p>
<p>Theme: craft as resistance to being cardboard "Uncle Security"; when to enforce rules vs when coffee buys human witness.</p>
<p><em>Genre:</em> workplace slice-of-life; gentle humor + ache.</p>
""",
)

story(
    "当 AI 开始设计婚礼",
    "When AI Starts Designing Weddings",
    "Ritual outsourcing, wedding-industrial complex, family face",
    """
<p>Engaged couple + planner triangle—bride ~28–32, engineer fiancé, parents on banquet table count. AI generates mood boards, seating, speech drafts, synthetic venue preview video.</p>
<table>
<tr><th>Source</th><th>Conflict</th></tr>
<tr><td>Bride</td><td>Personalized story</td></tr>
<tr><td>AI default</td><td>Pinterest homogenization</td></tr>
<tr><td>In-laws</td><td>Red vs white, hometown vs city</td></tr>
<tr><td>Budget</td><td>Subscription "luxury palette"</td></tr>
</table>
<p>Question: wedding for memory, performance, or merger compliance?</p>
<p><em>Genre:</em> domestic satire; light SF garnish.</p>
""",
)

story(
    "老小区的最后一家理发店",
    "The Last Barbershop in the Old Compound",
    "Community sacrament, aging trade, gentrification echo",
    """
<p>Master ~60s, ¥15–25 plain cut vs mall hundreds; radio news, hot towel ritual. Client roster = oral history—same style since 1980, migrant trusting only this mirror, quiet crop after chemo/divorce.</p>
<p>Plot: apprentice nephew, hand tremor, fire inspection, rent chain. Closing = losing time machine measured in snip cadence.</p>
<p><em>Genre:</em> nostalgic urban portrait; craft extinction sibling to repairman story.</p>
""",
)

story(
    "我们在共享办公空间里相遇",
    "We Met in a Coworking Space",
    "Gig loneliness, performative hustle, rented tribe",
    """
<p>Rotating third among three freelancers—burned-out ex-big-tech designer, failed-startup second-timer, returnee consultant. Glass walls, hot-desk lottery, cringey networking bingo, instant ramen at 9 p.m.</p>
<p>Bond forms at printer jams; coworking sells tribe but badge scans track who pays. Beats: launch party, client ghosting, hot-desk price double, affair in phone booth.</p>
<p><em>Genre:</em> startup satire; ensemble friendship.</p>
""",
)

story(
    "当 AI 开始审电影剧本",
    "When AI Starts Reviewing Screenplay Submissions",
    "Creative gatekeeping, streaming factory economics",
    """
<p>Screenwriter ~30s, agents push algorithmic coverage before human read. Portal scores likability, beat compliance, violence budget—3 a.m. auto-pass emails.</p>
<p>Moves: cynical beat inserts vs truthful rural drama that fails model; one human champion reading pdf on subway.</p>
<p><em>Genre:</em> meta industry satire with ache.</p>
""",
)

story(
    "异乡的深夜外卖员",
    "The Late-Night Delivery Rider in a Strange City",
    "Platform labor, heat-map geography, rider solidarity",
    """
<p>First-person rider ~25–35, ex-factory or student debt, tier-1/2 without hukou comfort—city known only as glow. Hours 10 p.m.–4 a.m.; algorithm bonus windows; ratings as boss.</p>
<p>Episodes: drunk white-collar, security beating, hospital dawn order, rider death rumor in group chat. Home: rural parents on video, rent bed-space, Spring Festival plan postponed forever.</p>
<p><em>Genre:</em> gig realism; urban noir lite.</p>
""",
)

story(
    "她决定辞去体制内工作",
    "She Decided to Leave Her Public-Sector Job",
    "Iron rice bowl, generational expectation, runway math",
    """
<p>Female civil servant ~30–38—education, street office, hospital admin; parents proud, partner split. Stack: meaningless overtime, promotion ceiling, petty corruption disgust, side skill itching, colleague overwork death.</p>
<h3>Phases</h3>
<ul>
<li>Fantasy → research → trial leave → letter in meeting season → insurance gap, parent tears, first freelance invoice.</li>
</ul>
<p>Not always triumphant startup—sometimes worse exploit job or scarred return.</p>
<p><em>Genre:</em> career transition realism.</p>
""",
)

story(
    "最后一个会修钟表的人",
    "The Last Person Who Still Fixes Clocks",
    "Temporal craft, slowness as service",
    """
<p>Analog horologist in shrinking stall—grandfather clocks, mechanical watches, unfunded plaza clock. City syncs to phone UTC; ticking room meditates or horrifies impatient visitors.</p>
<p>Plot: estate sale, heir wants melt for gold, museum digitization offer, shaking hands, YouTube teaching vs secrets dying.</p>
<p><em>Genre:</em> melancholy craft; time metaphor earned.</p>
""",
)

story(
    "我们在移民咨询办公室分手",
    "We Broke Up at the Immigration Consultancy Office",
    "Exit plan as relationship X-ray",
    """
<p>Couple late 20s–early 30s in agency glass room—points calculators, student vs skilled paths. Came to plan joint future; reveals incompatible risk: escape any cost vs PR safety net only if keeping Beijing condo.</p>
<p>Breakup quiet—elevator exit, deposit payment, shared Excel dream deleted.</p>
<p><em>Genre:</em> diaspora prelude; anti-romcom realism.</p>
""",
)

story(
    "当 AI 开始教钢琴",
    "When AI Starts Teaching Piano",
    "Embodiment in learning, tiger parent economics",
    """
<p>Teacher ~40s or student ~15—grade exam pressure; app gives pitch feedback, hand-position CV, examiner simulation. Teacher redundant except for rubato, grief, boredom discipline.</p>
<p>Recital contrasts MIDI-perfect vs messy human Chopin.</p>
<p><em>Genre:</em> education SF lite; sensory writing.</p>
""",
)

story(
    "老城厢里的民宿老板娘",
    "The B&B Owner in the Old City Quarter",
    "Performed heritage, platform ranking, solo business risk",
    """
<p>Host ~35–45, converted lane house, five rooms on platforms, lives in back cubicle. Guests: backpackers, influencers, cheating couple, family trashing Ming chair. Fire retrofit, neighbor wheel noise, seasonal famine.</p>
<p>Performs authenticity while secretly hating crowds; local boyfriend vs investor buyer.</p>
<p><em>Genre:</em> tourism economy portrait.</p>
""",
)

story(
    "他辞职去开货运无人机公司",
    "He Quit to Start a Freight Drone Company",
    "Founder hubris, regulatory gray zone, innovation theater",
    """
<p><strong>Lin Yue</strong>, ~32, leaves a stable SOE logistics desk to pitch last-mile freight drones with cofounder <strong>Du Wei</strong> (engineer, true believer). Demo day in a suburban industrial park draws local officials and a VC who loves the deck more than the hardware.</p>
<h3>Cycle portrayed</h3>
<ul>
<li>Pitch deck inflation — TAM slides bigger each week.</li>
<li>Regulatory CAAC gray zone — fly low, apologize later.</li>
<li>Beta crash in rain — team livestreams "learning moment."</li>
<li>Pivot to agricultural spray when mall delivery dream dies.</li>
</ul>
<p>Family dinner: parents ask when salary returns; girlfriend archives his hype videos. Media fluff piece titles him "young Musk of the county"; rainy-night field repair shows the real job.</p>
<p><strong>Theme:</strong> 2020s China innovation theater vs mundane compliance stack—not anti-tech, anti-myth.</p>
<p><em>Genre:</em> startup realism; founder hubris cycle.</p>
""",
)

story(
    "最后一个会纳鞋底的人",
    "The Last Person Who Still Soles Shoes",
    "Micro-repair grace, throwaway culture",
    """
<p>Street cobbler awl-and-thread, ¥30 vs disposable shoes; student sneakers, office heels, Liberation shoe nostalgia. Hand arthritis, street sweep forbidding stool, child refuses inheritance.</p>
<p>Pairs with phone repair and clocks—<strong>mending triangle</strong> in corpus.</p>
<p><em>Genre:</em> micro-portrait; manual dignity.</p>
""",
)

story(
    "我们在核酸检测点相爱",
    "We Fell in Love at the COVID Testing Site",
    "Period-specific romance, health code as deadline",
    """
<p>Bittersweet rom-com during mass testing—queue markers, 72-hour expiry as date deadline. Masked eye contact, WeChat from queue QR group; first full-face date when policy eases feels like remarriage.</p>
<p><em>Genre:</em> pandemic romance; already historical fiction for some readers.</p>
""",
)

story(
    "当 AI 开始写毕业论文",
    "When AI Starts Writing Theses",
    "Academic integrity melancholy, credential vs inquiry",
    """
<p>MA/PhD humanities/social science, distant advisor, AIGC detection arms race, roommate ghostwriting for cash. Blank page terror, parental investment, plagiarism committee email.</p>
<p><em>Genre:</em> campus realism; moral fatigue.</p>
""",
)

story(
    "她带着自闭症儿子搬家",
    "She Moved House with Her Autistic Son",
    "Care logistics, bureaucratic violence, advocacy",
    """
<p>Mother ~38–45, son ~8–12 on spectrum—school placement, noise complaints, elevator fear, district special-ed quota. Move from rent, divorce, or better therapy city.</p>
<p>Atlas: packing meltdown, route rehearsal, 物业 over corridor lighting, parent group at 2 a.m. Avoids inspiration porn—shows small wins and systemic failure.</p>
<p><em>Genre:</em> social issue fiction; intimate scale.</p>
""",
)

story(
    "异母异父的姐妹",
    "Stepsisters Who Share No Blood",
    "Blended family, gendered favoritism",
    """
<p>Parallel to stepbrothers: elder default parent, younger beauty/grade comparisons, shared bedroom cosmetics war, WeChat aunties comparing "who looks like bio dad."</p>
<p>18th birthday shoot rivalry; secret alliance; wedding seating as adulthood test.</p>
<p><em>Genre:</em> dual sister POV; YA-adjacent family.</p>
""",
)

story(
    "他在外包公司做完最后一个项目",
    "He Finished His Last Project at the Outsourcing Firm",
    "Offshore dev expendability, calm tragedy, resignation literature",
    """
<p><strong>Zhang Mo</strong>, ~29, body-shop developer billing hours to a FAANG-like client whose name redacts in every slide. Bench rumors precede every sprint; colleagues vanish mid-ticket without goodbye lunch.</p>
<p>Last project: boring CRUD on legacy module nobody in-house wants. KPI says close tickets, not understand system. He keeps personal notes in encrypted vault—delete day mandated.</p>
<h3>Last day beats</h3>
<ul>
<li>Badge return line longer than exit interview.</li>
<li>NDA reminder read at speed.</li>
<li>Group photo posted; nobody downloads.</li>
<li>Bike ride past new glass campus he will never enter.</li>
</ul>
<p><strong>Theme:</strong> global software chain's disposable human; dignity of craft without ownership.</p>
<p><em>Genre:</em> tech workplace; calm tragedy.</p>
""",
)

story(
    "当 AI 开始审病历",
    "When AI Starts Reviewing Medical Records",
    "Clinical gaze automated, moral injury",
    """
<p>Resident ~30s, EMR auto-coding, prior-auth summarizer, defensive medicine nudges. Patient compressed to ICD tags; night clicking approve on AI-drafted notes. Missed nuance on elder fall or psych patient.</p>
<p><em>Genre:</em> medical ethics; institutional realism.</p>
""",
)

story(
    "最后一个会包粽子的邻居",
    "The Last Neighbor Who Still Wraps Zongzi",
    "Festival gift labor, neighbor network",
    """
<p>Grandma wraps for whole building before Dragon Boat; younger residents buy Starbucks instead; bamboo leaf sourcing harder; HOA kitchen ban. Narrator learns fold; Shanghai vs hometown taste; community finishes pot or skips year.</p>
<p><em>Genre:</em> seasonal slice-of-life; food memory.</p>
""",
)

story(
    "我们在律师函里结婚",
    "We Got Married Through Lawyer Letters",
    "Marriage as limited partnership",
    """
<p>Prenup-heavy path after startup equity or inheritance panic—lawyers as wedding planners, clause negotiation replaces vows, families read PDF at dinner. Love via liability caps.</p>
<p><em>Genre:</em> rom-drama procedural.</p>
""",
)

story(
    "她决定不做全职妈妈",
    "She Decided Not to Be a Full-Time Mom",
    "Return-to-work backlash, childcare gap",
    """
<p>~34 after leave cliff—vague husband support, grandparent strike, daycare queue, mommy-tracked colleagues, Xiaohongshu guilt ads. Pump in bathroom interview; "two kids plan?" question.</p>
<p><em>Genre:</em> feminist workplace; domestic negotiation.</p>
""",
)

story(
    "当 AI 开始写舆情通报",
    "When AI Starts Writing PR Crisis Statements",
    "Apology template machine, reputational algorithm, crisis comms",
    """
<p><strong>He Qian</strong>, ~30, consumer-brand PR lead. A hot-mic scandal hits at peak sales season; the group chat demands a statement before lawyers finish reading the clip.</p>
<p>AI drafts a tearless apology in three tones ("sincere," "firm," "youthful"); sentiment bot graphs the trough hour-by-hour; executive wants language that sounds human but binds nothing legally.</p>
<h3>Night-of flow</h3>
<ul>
<li>Weibo hashtag spikes while intern schedules KOL rebuttals.</li>
<li>Legal strips adjectives; AI re-adds empathy phrases.</li>
<li>Coupon compensation wording A/B tested on focus panel.</li>
</ul>
<p>Compares 2019 handwritten apology posts with 2025 RLHF grovel—readers feel the gap between performance and repair.</p>
<p><em>Genre:</em> media crisis satire; institutional realism.</p>
""",
)

story(
    "老弄堂里的最后一个报摊",
    "The Last News Kiosk in the Old Lane",
    "Print decline, morning-city rhythm",
    """
<p>Uncle ~65, morning stack, lottery tickets; kids buy card recharge only; metro diverted foot traffic. Regulars: chess cadre, courier shade, narrator buying paper to feel date.</p>
<p><em>Genre:</em> urban miniature elegy.</p>
""",
)

story(
    "我们在离婚冷静期里复合",
    "We Reconciled During the Divorce Cooling-Off Period",
    "Policy window as emotional lab",
    """
<p>30-day cooling period app countdown—one frantic, one calm; family camps lobby; child asked which home. PRC divorce law change as structural clock, not legal guide.</p>
<p><em>Genre:</em> ambivalent reunion; marriage realism.</p>
""",
)

story(
    "最后一个会修收音机的爷爷",
    "Grandpa Who Still Fixes Radios",
    "Analog epistemology, intergenerational signal",
    """
<p>Balcony radio repair, shortwave memories; grandson solders while TikTok lives. Electronics market closes; Bluetooth speaker gift—insult or love?</p>
<p><em>Genre:</em> nostalgic tech vignette.</p>
""",
)

story(
    "当 AI 开始带实习律师",
    "When AI Starts Mentoring Intern Lawyers",
    "Apprenticeship collapse, law factory",
    """
<p>Intern ~24 with AI mentor plugin—research beats partners; senior associates sabotage or adapt; firm bills AI hours. Ethics: who signs wrong cite?</p>
<p><em>Genre:</em> legal workplace satire.</p>
""",
)

story(
    "她在外企学会说 No",
    "She Learned to Say No at the Multinational",
    "Boundary training, assertiveness tax",
    """
<p>~31 in US/EU HQ culture clash—China office overwork vs global leave; documented pushback labeled not team player; perf review in English.</p>
<p><em>Genre:</em> office realism; muted empowerment.</p>
""",
)

story(
    "我们在这个城市没有亲戚",
    "We Have No Relatives in This City",
    "Migrant couple atomization, chosen family limits",
    """
<p>Dual migrants from different provinces—childbirth without support, ER alone, Spring Festival two takeout boxes. Friend-as-family fails when someone moves.</p>
<p><em>Genre:</em> urban loneliness portrait.</p>
""",
)

story(
    "当 AI 开始写悼词",
    "When AI Starts Writing Eulogies",
    "Grief commoditized, digital legacy",
    """
<p>Funeral package includes AI eulogy from WeChat export—family disputes tone; affair paragraphs nearly included; human priest edits on phone in hearse.</p>
<p><em>Genre:</em> dark social satire.</p>
""",
)

story(
    "最后一个会手工面馆的师傅",
    "The Last Master of Hand-Pulled Noodles",
    "Culinary kinetic craft, body knowledge",
    """
<p>La mian master ~55, shoulder rhythm, flour humidity sense; frozen franchise next door; food blogger slow-mo vs master wanting eater not camera.</p>
<p><em>Genre:</em> food worker portrait; sensory motion.</p>
""",
)

story(
    "我们在派出所调解室和好",
    "We Made Up in the Police Mediation Room",
    "State enters marriage, de-escalation",
    """
<p>Neighbor called 110—mediation officer scripted, both ashamed, peace note signed, walk home silent or tender. Officer's seen-it-all compassion.</p>
<p><em>Genre:</em> single-location marriage realism.</p>
""",
)

story(
    "当 AI 开始写相亲资料",
    "When AI Starts Writing Dating Profiles",
    "Intimacy metrics, marriage market performance",
    """
<p>~29 office worker facing parental pressure—AI polishes height, income, hobbies into "high match rate" copy; dates feel like meeting one's own press release. Friend warns: optimized profile attracts wrong expectations.</p>
<p>Turning point: one honest sentence in bio changes who swipes right. Explores whether compatibility algorithms optimize marriage or performance.</p>
<p><em>Genre:</em> contemporary romance satire; light SF.</p>
""",
)

story(
    "我们在学区房面前分手",
    "We Broke Up Over the School-District Apartment",
    "Class mobility, parenting futures, property as love test",
    """
<p>Couple ~32 with toddler—one side pushes leveraged school-district buy, other refuses decade of rice-and-pickle repayment. Agents, in-laws, and "don't ruin the child's start" weaponized in every dinner.</p>
<p>Breakup not over affair but over <strong>risk model for a child's future</strong>. Ending may show one partner buying alone, or neither buying and guilt lingering.</p>
<p><em>Genre:</em> urban property drama; relationship realism.</p>
""",
)

HTML_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>48 Micro-Fiction Novellas — Story Index</title>
  <style>
    :root {
      --bg: #0f1419;
      --surface: #1a2332;
      --text: #e7ecf3;
      --muted: #8b9cb3;
      --accent: #6eb5ff;
      --border: #2d3a4f;
    }
    * { box-sizing: border-box; }
    body {
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.65;
      margin: 0;
      padding: 2rem 1rem 4rem;
      max-width: 52rem;
      margin-inline: auto;
    }
    header { margin-bottom: 2.5rem; border-bottom: 1px solid var(--border); padding-bottom: 1.5rem; }
    h1 { font-size: 1.75rem; font-weight: 600; margin: 0 0 0.5rem; }
    .subtitle { color: var(--muted); font-size: 1rem; margin: 0; }
    .intro { color: var(--muted); font-size: 0.95rem; margin-top: 1rem; }
    .story-list { list-style: none; padding: 0; margin: 0; }
    .story-list > li { margin-bottom: 0.35rem; }
    details {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }
    details + details { margin-top: 0.5rem; }
    summary {
      cursor: pointer;
      padding: 0.85rem 1rem;
      font-weight: 500;
      list-style: none;
      user-select: none;
    }
    summary::-webkit-details-marker { display: none; }
    summary::before {
      content: "▸ ";
      color: var(--accent);
      display: inline-block;
      transition: transform 0.15s ease;
    }
    details[open] summary::before { transform: rotate(90deg); }
    summary:hover { background: rgba(110, 181, 255, 0.06); }
    summary b { color: var(--text); }
    .en { color: var(--muted); font-weight: 400; font-size: 0.92em; }
    .tags { color: var(--accent); font-size: 0.85em; font-weight: 400; }
    .body {
      padding: 0 1rem 1.25rem;
      border-top: 1px solid var(--border);
      font-size: 0.95rem;
    }
    .body h3 { font-size: 1rem; margin: 1.25rem 0 0.5rem; color: var(--accent); }
    .body p { margin: 0.75rem 0; }
    .body ul { margin: 0.5rem 0; padding-left: 1.25rem; }
    .body table { width: 100%; border-collapse: collapse; margin: 0.75rem 0; font-size: 0.9em; }
    .body th, .body td { border: 1px solid var(--border); padding: 0.4rem 0.6rem; text-align: left; }
    .body th { background: rgba(110, 181, 255, 0.08); }
    .body blockquote.warning {
      margin: 1rem 0;
      padding: 0.75rem 1rem;
      border-left: 3px solid #e8a838;
      background: rgba(232, 168, 56, 0.08);
      color: var(--text);
      font-size: 0.92em;
    }
    footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.85rem; }
  </style>
</head>
<body>
  <header>
    <h1>48 Micro-Fiction Novellas</h1>
    <p class="subtitle">Story index — expandable synopses (English)</p>
    <p class="intro">Click any title to expand a full synopsis: characters, conflict, themes, and genre notes. Chinese titles preserved; body text in English for international readers.</p>
  </header>
  <ol class="story-list">
"""

HTML_FOOT = """
  </ol>
  <footer>
    <p>Index generated for reading navigation. Synopses are interpretive summaries, not official publisher copy.</p>
  </footer>
</body>
</html>
"""


def main():
    items = []
    for i, (cn, en, tags, body) in enumerate(STORIES, 1):
        items.append(f"""    <li>
      <details>
        <summary><b>《{cn}》</b> <span class="en">({en})</span> — <span class="tags">{tags}</span></summary>
        <div class="body">
{body}
        </div>
      </details>
    </li>""")
    html = HTML_HEAD + "\n".join(items) + HTML_FOOT
    out = Path(__file__).resolve().parent / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {len(STORIES)} stories to {out}")


if __name__ == "__main__":
    main()
