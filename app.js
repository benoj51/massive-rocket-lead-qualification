/**
 * Massive Rocket Lead Qualification Platform
 * Client-side application logic
 */

// ============================================
// API Configuration
// ============================================

const API_BASE_URL = "http://localhost:5000/api";
const RESEARCH_API_URL = "http://localhost:5001/api";

// ============================================
// ICP Configuration (mirrored from Python)
// ============================================

const ICP_CRITERIA = {
    revenue: {
        weight: 3,
        thresholds: [
            [0, 100_000_000, 0, "<$100M"],
            [100_000_000, 500_000_000, 1, "$100M-$500M"],
            [500_000_000, 1_000_000_000, 2, "$500M-$1B"],
            [1_000_000_000, Infinity, 3, ">$1B"]
        ]
    },
    employees: {
        weight: 2,
        thresholds: [
            [0, 500, 0, "<500"],
            [500, 1500, 1, "500-1,500"],
            [1500, 3000, 2, "1,500-3,000"],
            [3000, Infinity, 3, "3,000+"]
        ]
    },
    vertical: {
        weight: 3,
        scores: {
            qsr: 3, retail: 3, travel: 3, fintech: 3, delivery: 3, convenience: 3,
            telecom: 2, media: 2, healthcare: 2, smart_home: 2,
            saas: 1, technology: 1, manufacturing: 1, other: 1
        },
        default: 1
    },
    tech_stack: {
        weight: 3,
        scores: {
            braze_snowflake: 3,
            braze_warehouse: 2,
            braze_only: 1,
            no_braze: 0
        }
    },
    complexity: {
        weight: 2,
        scores: {
            multi_brand_multi_market: 3,
            multi_brand: 2,
            multi_market: 2,
            enterprise: 2,
            single: 1,
            simple: 0
        }
    },
    deal_size: {
        weight: 3,
        thresholds: [
            [0, 10_000, 0, "<£10k/mo"],
            [10_000, 30_000, 1, "£10k-£30k/mo"],
            [30_000, 50_000, 2, "£30k-£50k/mo"],
            [50_000, Infinity, 3, ">£50k/mo"]
        ]
    },
    region: {
        weight: 1,
        scores: {
            nam_emea: 3, global: 3,
            nam: 2, emea: 2,
            apac: 1, other: 1
        }
    }
};

const MAX_WEIGHTED_SCORE = Object.values(ICP_CRITERIA).reduce((sum, c) => sum + c.weight * 3, 0); // 51

const THRESHOLDS = {
    qualify_in: 7.0,
    borderline_low: 5.0
};

const TECH_KEYWORDS = {
    braze: ["braze"],
    snowflake: ["snowflake"],
    data_warehouse: ["bigquery", "redshift", "databricks", "synapse", "warehouse"]
};

const VERTICAL_LABELS = {
    qsr: "QSR / Quick Service Restaurant",
    retail: "Retail / E-commerce",
    travel: "Travel & Hospitality",
    fintech: "Fintech / Financial Services",
    delivery: "Delivery / Logistics",
    convenience: "Convenience / C-Store",
    telecom: "Telecom",
    media: "Media & Entertainment",
    healthcare: "Healthcare",
    smart_home: "Smart Home / IoT",
    saas: "SaaS / Technology",
    manufacturing: "Manufacturing",
    other: "Other"
};

const REGION_LABELS = {
    nam: "North America (NAM)",
    emea: "Europe (EMEA)",
    apac: "Asia Pacific (APAC)",
    nam_emea: "NAM + EMEA",
    global: "Global / Multi-Region"
};

const COMPLEXITY_LABELS = {
    multi_brand_multi_market: "Multi-Brand + Multi-Market",
    multi_brand: "Multi-Brand",
    multi_market: "Multi-Market / Global",
    enterprise: "Enterprise / Large",
    single: "Single Brand / Region"
};

// ============================================
// Parsing Functions
// ============================================

function parseRevenue(revenueStr) {
    if (!revenueStr) return null;

    let str = revenueStr.toString().toLowerCase().replace(/,/g, "").replace(/ /g, "");

    const multipliers = {
        b: 1_000_000_000, bn: 1_000_000_000, billion: 1_000_000_000,
        m: 1_000_000, mn: 1_000_000, million: 1_000_000,
        k: 1_000, thousand: 1_000
    };

    // Remove currency symbols
    ["$", "£", "€", "usd", "gbp", "eur"].forEach(sym => {
        str = str.replace(sym, "");
    });

    const match = str.match(/([\d.]+)\s*([a-z]*)/);
    if (match) {
        const number = parseFloat(match[1]);
        const suffix = match[2];
        const multiplier = multipliers[suffix] || 1;
        return number * multiplier;
    }

    const parsed = parseFloat(str);
    return isNaN(parsed) ? null : parsed;
}

function parseEmployees(employeeStr) {
    if (!employeeStr) return null;

    let str = employeeStr.toString().toLowerCase().replace(/,/g, "").replace(/ /g, "");

    // Handle ranges
    if (str.includes("-")) {
        const parts = str.split("-");
        const upper = parts[parts.length - 1].replace("+", "").replace("k", "000");
        const parsed = parseInt(upper);
        return isNaN(parsed) ? null : parsed;
    }

    str = str.replace("+", "");

    if (str.endsWith("k")) {
        const num = parseFloat(str.slice(0, -1));
        return isNaN(num) ? null : Math.round(num * 1000);
    }

    const parsed = parseInt(str);
    return isNaN(parsed) ? null : parsed;
}

// ============================================
// Scoring Functions
// ============================================

function scoreNumericCriterion(value, config) {
    if (value === null) return { score: 0, label: "Unknown" };

    for (const [low, high, score, label] of config.thresholds) {
        if (value >= low && value < high) {
            return { score, label };
        }
    }
    return { score: 0, label: "Out of range" };
}

function scoreTechStack(techData) {
    if (!techData) return { score: 0, label: "Unknown" };

    const techLower = techData.toString().toLowerCase();

    const hasBraze = TECH_KEYWORDS.braze.some(kw => techLower.includes(kw));
    const hasSnowflake = TECH_KEYWORDS.snowflake.some(kw => techLower.includes(kw));
    const hasWarehouse = hasSnowflake || TECH_KEYWORDS.data_warehouse.some(kw => techLower.includes(kw));

    if (hasBraze && hasSnowflake) {
        return { score: 3, label: "Braze + Snowflake" };
    } else if (hasBraze && hasWarehouse) {
        return { score: 2, label: "Braze + Data Warehouse" };
    } else if (hasBraze) {
        return { score: 1, label: "Braze Only" };
    }
    return { score: 0, label: "No Braze Detected" };
}

function calculateICPScore(companyData) {
    const breakdown = {};
    let totalWeighted = 0;

    // Revenue
    const revenue = parseRevenue(companyData.revenue);
    let result = scoreNumericCriterion(revenue, ICP_CRITERIA.revenue);
    let weight = ICP_CRITERIA.revenue.weight;
    breakdown.revenue = {
        rawScore: result.score,
        weight,
        weighted: result.score * weight,
        value: result.label,
        maxWeighted: weight * 3
    };
    totalWeighted += result.score * weight;

    // Employees
    const employees = parseEmployees(companyData.employees);
    result = scoreNumericCriterion(employees, ICP_CRITERIA.employees);
    weight = ICP_CRITERIA.employees.weight;
    breakdown.employees = {
        rawScore: result.score,
        weight,
        weighted: result.score * weight,
        value: result.label,
        maxWeighted: weight * 3
    };
    totalWeighted += result.score * weight;

    // Vertical
    const verticalScore = ICP_CRITERIA.vertical.scores[companyData.vertical] ?? ICP_CRITERIA.vertical.default;
    const verticalLabel = VERTICAL_LABELS[companyData.vertical] || companyData.vertical || "Unknown";
    weight = ICP_CRITERIA.vertical.weight;
    breakdown.vertical = {
        rawScore: verticalScore,
        weight,
        weighted: verticalScore * weight,
        value: verticalLabel,
        maxWeighted: weight * 3
    };
    totalWeighted += verticalScore * weight;

    // Tech Stack
    result = scoreTechStack(companyData.techStack);
    weight = ICP_CRITERIA.tech_stack.weight;
    breakdown.techStack = {
        rawScore: result.score,
        weight,
        weighted: result.score * weight,
        value: result.label,
        maxWeighted: weight * 3
    };
    totalWeighted += result.score * weight;

    // Complexity
    const complexityScore = ICP_CRITERIA.complexity.scores[companyData.complexity] ?? 1;
    const complexityLabel = COMPLEXITY_LABELS[companyData.complexity] || "Unknown";
    weight = ICP_CRITERIA.complexity.weight;
    breakdown.complexity = {
        rawScore: complexityScore,
        weight,
        weighted: complexityScore * weight,
        value: complexityLabel,
        maxWeighted: weight * 3
    };
    totalWeighted += complexityScore * weight;

    // Deal Size (estimated based on company size)
    let dealSizeScore = 1; // Default estimate
    let dealSizeLabel = "Estimated";
    if (revenue) {
        if (revenue >= 1_000_000_000) {
            dealSizeScore = 3;
            dealSizeLabel = ">£50k/mo (est.)";
        } else if (revenue >= 500_000_000) {
            dealSizeScore = 2;
            dealSizeLabel = "£30k-£50k/mo (est.)";
        } else if (revenue >= 100_000_000) {
            dealSizeScore = 1;
            dealSizeLabel = "£10k-£30k/mo (est.)";
        }
    }
    weight = ICP_CRITERIA.deal_size.weight;
    breakdown.dealSize = {
        rawScore: dealSizeScore,
        weight,
        weighted: dealSizeScore * weight,
        value: dealSizeLabel,
        maxWeighted: weight * 3
    };
    totalWeighted += dealSizeScore * weight;

    // Region
    const regionScore = ICP_CRITERIA.region.scores[companyData.region] ?? 1;
    const regionLabel = REGION_LABELS[companyData.region] || "Unknown";
    weight = ICP_CRITERIA.region.weight;
    breakdown.region = {
        rawScore: regionScore,
        weight,
        weighted: regionScore * weight,
        value: regionLabel,
        maxWeighted: weight * 3
    };
    totalWeighted += regionScore * weight;

    // Normalize to 10-point scale
    const normalizedScore = Math.round((totalWeighted / MAX_WEIGHTED_SCORE) * 10 * 10) / 10;

    // Determine status
    let status, statusDisplay;
    if (normalizedScore >= THRESHOLDS.qualify_in) {
        status = "qualify_in";
        statusDisplay = "Qualify In";
    } else if (normalizedScore >= THRESHOLDS.borderline_low) {
        status = "borderline";
        statusDisplay = "Borderline";
    } else {
        status = "qualify_out";
        statusDisplay = "Qualify Out";
    }

    return {
        totalWeighted,
        maxWeighted: MAX_WEIGHTED_SCORE,
        normalizedScore,
        status,
        statusDisplay,
        breakdown
    };
}

function checkHardDisqualifiers(companyData) {
    const disqualifiers = [];

    const revenue = parseRevenue(companyData.revenue);
    if (revenue && revenue < 50_000_000) {
        disqualifiers.push("Revenue under $50M");
    }

    const employees = parseEmployees(companyData.employees);
    if (employees && employees < 200) {
        disqualifiers.push("Employee count under 200");
    }

    const techStack = (companyData.techStack || "").toLowerCase();
    if (techStack.includes("no braze") || (!techStack.includes("braze") && techStack.length > 0)) {
        // Only flag if we have tech data but no braze
        if (techStack.length > 5 && !techStack.includes("braze")) {
            disqualifiers.push("No Braze detected in known stack");
        }
    }

    return disqualifiers;
}

function identifyPositiveSignals(companyData) {
    const signals = [];

    const techStack = (companyData.techStack || "").toLowerCase();
    if (techStack.includes("braze") && techStack.includes("snowflake")) {
        signals.push("Braze + Snowflake already in stack");
    }

    const source = (companyData.source || "").toLowerCase();
    if (source.includes("braze") || source.includes("hightouch") || source.includes("referral")) {
        signals.push("Partner referral (Braze/Hightouch)");
    }

    if (companyData.complexity === "multi_brand_multi_market") {
        signals.push("High complexity enterprise");
    }

    const revenue = parseRevenue(companyData.revenue);
    if (revenue && revenue >= 1_000_000_000) {
        signals.push("$1B+ revenue tier");
    }

    const employees = parseEmployees(companyData.employees);
    if (employees && employees >= 3000) {
        signals.push("3,000+ employees");
    }

    return signals;
}

function generateNextSteps(result, companyData) {
    const steps = [];

    if (result.status === "qualify_in") {
        steps.push("Schedule discovery call with CMO/VP Marketing");
        steps.push("Prepare case study from similar vertical");

        if (result.breakdown.techStack.rawScore < 3) {
            steps.push("Research current tech stack in detail");
        }

        steps.push("Identify additional stakeholders (CDO, CIO)");
        steps.push("Sync to Notion pipeline for tracking");
    } else if (result.status === "borderline") {
        steps.push("Gather more information on tech stack and budget");
        steps.push("Identify executive sponsor potential");
        steps.push("Research competitor engagement (Merkle, Accenture)");
        steps.push("Schedule exploratory call to assess fit");
    } else {
        steps.push("Review for potential future opportunity");
        steps.push("Add to nurture list for market changes");
        steps.push("Consider for partner referral if outside ICP");
    }

    return steps;
}

// ============================================
// UI State Management
// ============================================

let currentStep = 1;
let companyData = {};

function updateStepIndicator(step) {
    document.querySelectorAll(".step").forEach((el, idx) => {
        const stepNum = idx + 1;
        el.classList.remove("active", "completed");
        if (stepNum === step) {
            el.classList.add("active");
        } else if (stepNum < step) {
            el.classList.add("completed");
        }
    });
}

function showStep(step) {
    currentStep = step;
    updateStepIndicator(step);

    document.querySelectorAll(".step-section").forEach(section => {
        section.classList.remove("active");
    });

    document.getElementById(`step-${step}`).classList.add("active");
}

function collectFormData() {
    return {
        companyName: document.getElementById("company-name").value.trim(),
        companyUrl: document.getElementById("company-url").value.trim(),
        revenue: document.getElementById("revenue").value.trim(),
        employees: document.getElementById("employees").value.trim(),
        vertical: document.getElementById("vertical").value,
        region: document.getElementById("region").value,
        techStack: document.getElementById("tech-stack").value.trim(),
        complexity: document.getElementById("complexity").value,
        source: document.getElementById("source").value.trim()
    };
}

function updateBrandPreview(data) {
    // Update brand header
    const initial = data.companyName.charAt(0).toUpperCase();
    document.querySelector("#step-2 .brand-initial").textContent = initial;
    document.getElementById("preview-company-name").textContent = data.companyName;

    const urlEl = document.getElementById("preview-url");
    if (data.companyUrl) {
        urlEl.textContent = data.companyUrl;
        urlEl.href = data.companyUrl.startsWith("http") ? data.companyUrl : `https://${data.companyUrl}`;
        urlEl.style.display = "block";
    } else {
        urlEl.style.display = "none";
    }

    // Update preview grid
    document.getElementById("preview-revenue").textContent = data.revenue || "—";
    document.getElementById("preview-employees").textContent = data.employees || "—";
    document.getElementById("preview-vertical").textContent = VERTICAL_LABELS[data.vertical] || data.vertical || "—";
    document.getElementById("preview-region").textContent = REGION_LABELS[data.region] || data.region || "—";
    document.getElementById("preview-complexity").textContent = COMPLEXITY_LABELS[data.complexity] || data.complexity || "—";
    document.getElementById("preview-source").textContent = data.source || "—";

    // Update tech stack tags
    const techContainer = document.getElementById("preview-tech-stack");
    techContainer.innerHTML = "";

    if (data.techStack) {
        const techs = data.techStack.split(",").map(t => t.trim()).filter(t => t);
        techs.forEach(tech => {
            const tag = document.createElement("span");
            tag.className = "tech-tag";
            tag.textContent = tech;

            // Add special styling for key tools
            if (tech.toLowerCase().includes("braze")) {
                tag.classList.add("braze");
            } else if (tech.toLowerCase().includes("snowflake")) {
                tag.classList.add("snowflake");
            }

            techContainer.appendChild(tag);
        });
    } else {
        techContainer.innerHTML = '<span class="tech-tag">—</span>';
    }
}

function displayResults(data, scoreResult) {
    // Update result header
    const initial = data.companyName.charAt(0).toUpperCase();
    document.querySelector("#step-3 .brand-initial").textContent = initial;
    document.getElementById("result-company-name").textContent = data.companyName;

    // Update status
    const statusEl = document.getElementById("result-status");
    statusEl.textContent = scoreResult.statusDisplay;
    statusEl.className = `score-status ${scoreResult.status.replace("_", "-")}`;

    // Update score
    document.getElementById("result-score").textContent = scoreResult.normalizedScore;

    // Update score breakdown
    const breakdownContainer = document.getElementById("score-breakdown");
    breakdownContainer.innerHTML = "";

    const criteriaOrder = [
        { key: "revenue", label: "Revenue" },
        { key: "employees", label: "Employees" },
        { key: "vertical", label: "Vertical" },
        { key: "techStack", label: "Tech Stack" },
        { key: "complexity", label: "Complexity" },
        { key: "dealSize", label: "Deal Size" },
        { key: "region", label: "Region" }
    ];

    criteriaOrder.forEach(({ key, label }) => {
        const item = scoreResult.breakdown[key];
        const percentage = (item.weighted / item.maxWeighted) * 100;

        let barClass = "high";
        if (percentage < 33) barClass = "low";
        else if (percentage < 66) barClass = "medium";

        const html = `
            <div class="score-item">
                <span class="score-item-label">${label}</span>
                <div class="score-bar-container">
                    <div class="score-bar ${barClass}" style="width: ${percentage}%"></div>
                </div>
                <span class="score-item-value">${item.weighted}/${item.maxWeighted}</span>
            </div>
        `;
        breakdownContainer.innerHTML += html;
    });

    // Update signals
    const signalsContainer = document.getElementById("signals-section");
    signalsContainer.innerHTML = "";

    const positiveSignals = identifyPositiveSignals(data);
    const disqualifiers = checkHardDisqualifiers(data);

    if (positiveSignals.length > 0) {
        const html = `
            <div class="signals-group">
                <div class="signals-title positive">
                    <svg class="icon" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                    </svg>
                    Positive Signals
                </div>
                <div class="signals-list">
                    ${positiveSignals.map(s => `<span class="signal-tag positive">${s}</span>`).join("")}
                </div>
            </div>
        `;
        signalsContainer.innerHTML += html;
    }

    if (disqualifiers.length > 0) {
        const html = `
            <div class="signals-group">
                <div class="signals-title negative">
                    <svg class="icon" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
                    </svg>
                    Concerns
                </div>
                <div class="signals-list">
                    ${disqualifiers.map(d => `<span class="signal-tag negative">${d}</span>`).join("")}
                </div>
            </div>
        `;
        signalsContainer.innerHTML += html;
    }

    // Update next steps
    const nextSteps = generateNextSteps(scoreResult, data);
    const nextStepsContainer = document.getElementById("next-steps");
    nextStepsContainer.innerHTML = nextSteps.map((step, idx) => `
        <div class="next-step-item">
            <span class="next-step-number">${idx + 1}</span>
            <span class="next-step-text">${step}</span>
        </div>
    `).join("");
}

function exportReport() {
    const data = companyData;
    const result = calculateICPScore(data);

    const report = `
MASSIVE ROCKET LEAD QUALIFICATION REPORT
========================================

Company: ${data.companyName}
URL: ${data.companyUrl || "N/A"}
Date: ${new Date().toLocaleDateString()}

ICP SCORE: ${result.normalizedScore}/10 - ${result.statusDisplay.toUpperCase()}

SCORE BREAKDOWN
---------------
Revenue:     ${result.breakdown.revenue.value} (${result.breakdown.revenue.weighted}/${result.breakdown.revenue.maxWeighted} pts)
Employees:   ${result.breakdown.employees.value} (${result.breakdown.employees.weighted}/${result.breakdown.employees.maxWeighted} pts)
Vertical:    ${result.breakdown.vertical.value} (${result.breakdown.vertical.weighted}/${result.breakdown.vertical.maxWeighted} pts)
Tech Stack:  ${result.breakdown.techStack.value} (${result.breakdown.techStack.weighted}/${result.breakdown.techStack.maxWeighted} pts)
Complexity:  ${result.breakdown.complexity.value} (${result.breakdown.complexity.weighted}/${result.breakdown.complexity.maxWeighted} pts)
Deal Size:   ${result.breakdown.dealSize.value} (${result.breakdown.dealSize.weighted}/${result.breakdown.dealSize.maxWeighted} pts)
Region:      ${result.breakdown.region.value} (${result.breakdown.region.weighted}/${result.breakdown.region.maxWeighted} pts)

TOTAL: ${result.totalWeighted}/${result.maxWeighted} weighted points

POSITIVE SIGNALS
----------------
${identifyPositiveSignals(data).map(s => `• ${s}`).join("\n") || "None identified"}

CONCERNS
--------
${checkHardDisqualifiers(data).map(d => `• ${d}`).join("\n") || "None identified"}

NEXT STEPS
----------
${generateNextSteps(result, data).map((s, i) => `${i + 1}. ${s}`).join("\n")}

---
Generated by Massive Rocket Lead Qualification Platform
    `.trim();

    const blob = new Blob([report], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${data.companyName.replace(/\s+/g, "_")}_qualification_report.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ============================================
// Notion Integration
// ============================================

let notionConfigured = false;

async function checkNotionStatus() {
    try {
        const response = await fetch(`${API_BASE_URL}/config`);
        const data = await response.json();
        notionConfigured = data.notion_configured;
        updateNotionButton();
    } catch (error) {
        console.log("Server not running - Notion sync unavailable");
        notionConfigured = false;
        updateNotionButton();
    }
}

function updateNotionButton() {
    const btn = document.getElementById("btn-sync-notion");
    if (btn) {
        if (notionConfigured) {
            btn.classList.remove("btn-disabled");
            btn.title = "Save to Notion";
        } else {
            btn.classList.add("btn-disabled");
            btn.title = "Notion not configured - start server with API keys";
        }
    }
}

async function syncToNotion() {
    if (!notionConfigured) {
        showNotification("Notion not configured. Start the server with NOTION_API_KEY and NOTION_DATABASE_ID.", "error");
        return;
    }

    const btn = document.getElementById("btn-sync-notion");
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="loading-spinner"></span> Saving...';
    btn.disabled = true;

    try {
        const scoreResult = calculateICPScore(companyData);
        const nextSteps = generateNextSteps(scoreResult, companyData);
        const positiveSignals = identifyPositiveSignals(companyData);
        const disqualifiers = checkHardDisqualifiers(companyData);

        const payload = {
            ...companyData,
            normalizedScore: scoreResult.normalizedScore,
            status: scoreResult.status,
            statusDisplay: scoreResult.statusDisplay,
            breakdown: scoreResult.breakdown,
            totalWeighted: scoreResult.totalWeighted,
            maxWeighted: scoreResult.maxWeighted,
            nextSteps,
            positiveSignals,
            disqualifiers
        };

        const response = await fetch(`${API_BASE_URL}/sync-to-notion`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        const result = await response.json();

        if (result.success) {
            showNotification(`Lead ${result.action} in Notion!`, "success");
            if (result.page_url) {
                // Add link to view in Notion
                setTimeout(() => {
                    if (confirm("Open the lead in Notion?")) {
                        window.open(result.page_url, "_blank");
                    }
                }, 500);
            }
        } else {
            showNotification(`Error: ${result.error}`, "error");
        }
    } catch (error) {
        showNotification(`Failed to sync: ${error.message}`, "error");
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

function showNotification(message, type = "info") {
    // Remove existing notification
    const existing = document.querySelector(".notification");
    if (existing) existing.remove();

    const notification = document.createElement("div");
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <span>${message}</span>
        <button class="notification-close">&times;</button>
    `;

    document.body.appendChild(notification);

    // Auto-hide after 5 seconds
    setTimeout(() => {
        notification.classList.add("fade-out");
        setTimeout(() => notification.remove(), 300);
    }, 5000);

    // Close button
    notification.querySelector(".notification-close").addEventListener("click", () => {
        notification.remove();
    });
}

// ============================================
// Company Research
// ============================================

let researchData = null;

async function checkResearchStatus() {
    try {
        const response = await fetch(`${RESEARCH_API_URL}/research/config`);
        const data = await response.json();
        return data.research_available;
    } catch (error) {
        console.log("Research server not running");
        return false;
    }
}

async function researchCompany() {
    const companyName = document.getElementById("company-name").value.trim();
    const companyUrl = document.getElementById("company-url").value.trim();

    if (!companyName) {
        showNotification("Please enter a company name first", "error");
        return;
    }

    const btn = document.getElementById("btn-research");
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="loading-spinner"></span> Researching...';
    btn.disabled = true;

    try {
        const response = await fetch(`${RESEARCH_API_URL}/research`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                company_name: companyName,
                company_url: companyUrl
            })
        });

        const result = await response.json();

        if (result.success) {
            researchData = result.data;
            displayResearchResults(result.data);
            showNotification("Research complete!", "success");
        } else {
            showNotification(`Research failed: ${result.error}`, "error");
        }
    } catch (error) {
        showNotification(`Research failed: ${error.message}. Make sure research server is running on port 5001.`, "error");
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

function displayResearchResults(data) {
    const container = document.getElementById("research-results");
    const grid = document.getElementById("research-grid");
    const description = document.getElementById("research-description");
    const confidence = document.getElementById("research-confidence");

    // Set description
    description.textContent = data.description || "No description available";

    // Set confidence
    confidence.textContent = `${data.confidence || "Medium"} Confidence`;
    confidence.className = "research-confidence";
    if (data.confidence === "Low") confidence.classList.add("low");
    else if (data.confidence === "Medium") confidence.classList.add("medium");

    // Build research grid
    const fields = [
        { key: "revenue", label: "Revenue", source: "revenue_source" },
        { key: "employees", label: "Employees", source: "employees_source" },
        { key: "vertical", label: "Vertical", source: null },
        { key: "headquarters", label: "Headquarters", source: null },
        { key: "regions", label: "Regions", source: null },
        { key: "tech_stack", label: "Tech Stack", source: "tech_stack_source" },
        { key: "complexity", label: "Complexity", source: null }
    ];

    grid.innerHTML = fields.map(field => {
        const value = data[field.key] || "Unknown";
        const source = field.source ? data[field.source] : null;

        return `
            <div class="research-item">
                <span class="research-item-label">${field.label}</span>
                <span class="research-item-value">${value}</span>
                ${source ? `<span class="research-item-source">${source}</span>` : ""}
            </div>
        `;
    }).join("");

    // Add notable info if present
    if (data.notable_info && data.notable_info !== "Unknown") {
        grid.innerHTML += `
            <div class="research-item" style="grid-column: 1 / -1;">
                <span class="research-item-label">Notable Info</span>
                <span class="research-item-value">${data.notable_info}</span>
            </div>
        `;
    }

    container.classList.remove("hidden");
}

function applyResearchToForm() {
    if (!researchData) return;

    // Map research data to form fields
    if (researchData.revenue && researchData.revenue !== "Unknown") {
        document.getElementById("revenue").value = researchData.revenue;
    }

    if (researchData.employees && researchData.employees !== "Unknown") {
        document.getElementById("employees").value = researchData.employees;
    }

    if (researchData.tech_stack && researchData.tech_stack !== "Unknown") {
        document.getElementById("tech-stack").value = researchData.tech_stack;
    }

    // Map vertical
    const verticalMap = {
        "QSR": "qsr",
        "Retail": "retail",
        "Travel & Hospitality": "travel",
        "Fintech": "fintech",
        "Delivery": "delivery",
        "Convenience": "convenience",
        "Telecom": "telecom",
        "Media & Entertainment": "media",
        "Healthcare": "healthcare",
        "SaaS/Technology": "saas",
        "Manufacturing": "manufacturing"
    };

    if (researchData.vertical) {
        const verticalKey = verticalMap[researchData.vertical] || "other";
        document.getElementById("vertical").value = verticalKey;
    }

    // Map region
    const regionStr = (researchData.regions || "").toLowerCase();
    if (regionStr.includes("global") || (regionStr.includes("america") && regionStr.includes("europe") && regionStr.includes("asia"))) {
        document.getElementById("region").value = "global";
    } else if (regionStr.includes("america") && regionStr.includes("europe")) {
        document.getElementById("region").value = "nam_emea";
    } else if (regionStr.includes("america") || regionStr.includes("us") || regionStr.includes("usa")) {
        document.getElementById("region").value = "nam";
    } else if (regionStr.includes("europe") || regionStr.includes("uk")) {
        document.getElementById("region").value = "emea";
    } else if (regionStr.includes("asia") || regionStr.includes("pacific")) {
        document.getElementById("region").value = "apac";
    }

    // Map complexity
    const complexityStr = (researchData.complexity || "").toLowerCase();
    if (complexityStr.includes("multi-brand") && complexityStr.includes("multi-market")) {
        document.getElementById("complexity").value = "multi_brand_multi_market";
    } else if (complexityStr.includes("multi-brand")) {
        document.getElementById("complexity").value = "multi_brand";
    } else if (complexityStr.includes("multi-market") || complexityStr.includes("global")) {
        document.getElementById("complexity").value = "multi_market";
    } else if (complexityStr.includes("enterprise")) {
        document.getElementById("complexity").value = "enterprise";
    }

    // Hide research panel
    document.getElementById("research-results").classList.add("hidden");
    showNotification("Research data applied to form", "success");
}

function dismissResearch() {
    document.getElementById("research-results").classList.add("hidden");
    researchData = null;
}

// ============================================
// Event Listeners
// ============================================

document.addEventListener("DOMContentLoaded", () => {
    // Check Notion status on load
    checkNotionStatus();

    // Research button
    document.getElementById("btn-research").addEventListener("click", researchCompany);
    document.getElementById("btn-apply-research").addEventListener("click", applyResearchToForm);
    document.getElementById("btn-dismiss-research").addEventListener("click", dismissResearch);

    // Form submission (Step 1 -> Step 2)
    document.getElementById("company-form").addEventListener("submit", (e) => {
        e.preventDefault();
        companyData = collectFormData();

        if (!companyData.companyName) {
            alert("Please enter a company name");
            return;
        }

        updateBrandPreview(companyData);
        showStep(2);
    });

    // Back button (Step 2 -> Step 1)
    document.getElementById("btn-back").addEventListener("click", () => {
        showStep(1);
    });

    // Confirm button (Step 2 -> Step 3)
    document.getElementById("btn-confirm").addEventListener("click", () => {
        const scoreResult = calculateICPScore(companyData);
        displayResults(companyData, scoreResult);
        showStep(3);
    });

    // New lead button (Step 3 -> Step 1)
    document.getElementById("btn-new-lead").addEventListener("click", () => {
        document.getElementById("company-form").reset();
        companyData = {};
        showStep(1);
    });

    // Export button
    document.getElementById("btn-export").addEventListener("click", exportReport);

    // Notion sync button
    document.getElementById("btn-sync-notion").addEventListener("click", syncToNotion);

    // Smooth scroll for nav link
    document.querySelector('a[href="#why-mr"]').addEventListener("click", (e) => {
        if (currentStep === 3) {
            e.preventDefault();
            document.getElementById("why-mr").scrollIntoView({ behavior: "smooth" });
        }
    });
});
