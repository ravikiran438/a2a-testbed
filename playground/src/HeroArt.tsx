// Liquid-glass hero band for the playground Home page. Self-contained SVG —
// scales responsively via viewBox, no hosted asset. Depicts the governed stack:
// the A2A agent network -> ACS verdict -> AG-UI human interrupt.

export function HeroArt() {
  return (
    <svg
      className="hero-art-svg"
      viewBox="0 0 1200 520"
      role="img"
      aria-label="A governed agent network: A2A agents, an ACS governance shield, and an AG-UI human-in-the-loop interrupt."
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="ha-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#0b1026" />
          <stop offset="0.5" stopColor="#241445" />
          <stop offset="1" stopColor="#06222e" />
        </linearGradient>
        <radialGradient id="ha-orbA" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#ff7ac6" stopOpacity="0.9" />
          <stop offset="1" stopColor="#ff7ac6" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="ha-orbB" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#5cf2e6" stopOpacity="0.85" />
          <stop offset="1" stopColor="#5cf2e6" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="ha-orbC" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#8b7bff" stopOpacity="0.9" />
          <stop offset="1" stopColor="#8b7bff" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="ha-glass" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.22" />
          <stop offset="0.5" stopColor="#ffffff" stopOpacity="0.08" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0.05" />
        </linearGradient>
        <linearGradient id="ha-edge" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.7" />
          <stop offset="0.4" stopColor="#ffffff" stopOpacity="0.12" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0.35" />
        </linearGradient>
        <linearGradient id="ha-flow" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#7aa2ff" />
          <stop offset="0.55" stopColor="#b07bff" />
          <stop offset="1" stopColor="#ff9e6b" />
        </linearGradient>
        <linearGradient id="ha-chipBlue" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#9ec1ff" stopOpacity="0.35" />
          <stop offset="1" stopColor="#3b6fe0" stopOpacity="0.18" />
        </linearGradient>
        <linearGradient id="ha-chipAmber" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffd9b0" stopOpacity="0.4" />
          <stop offset="1" stopColor="#e07b2a" stopOpacity="0.2" />
        </linearGradient>
        <filter id="ha-soft" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="34" />
        </filter>
        <filter id="ha-blur8" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="7" />
        </filter>
        <filter id="ha-shadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="10" stdDeviation="18" floodColor="#000000" floodOpacity="0.35" />
        </filter>
      </defs>

      <rect width="1200" height="520" rx="28" fill="url(#ha-bg)" />
      <circle cx="240" cy="120" r="210" fill="url(#ha-orbA)" filter="url(#ha-soft)" />
      <circle cx="1000" cy="140" r="230" fill="url(#ha-orbB)" filter="url(#ha-soft)" />
      <circle cx="640" cy="470" r="250" fill="url(#ha-orbC)" filter="url(#ha-soft)" />
      <g stroke="#ffffff" strokeOpacity="0.05">
        <path d="M0 170 H1200 M0 350 H1200 M300 0 V520 M600 0 V520 M900 0 V520" />
      </g>

      {/* flow line A2A -> ACS -> AG-UI */}
      <path
        d="M250 300 C 380 300, 430 300, 560 300 S 760 300, 940 300"
        fill="none"
        stroke="url(#ha-flow)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeOpacity="0.9"
      />
      <circle cx="250" cy="300" r="5" fill="#7aa2ff" />
      <circle cx="940" cy="300" r="5" fill="#ff9e6b" />

      {/* LEFT — A2A network */}
      <g filter="url(#ha-shadow)">
        <rect
          x="64"
          y="190"
          width="230"
          height="230"
          rx="26"
          fill="url(#ha-glass)"
          stroke="url(#ha-edge)"
          strokeWidth="1.5"
        />
      </g>
      <text x="86" y="226" fill="#dbe4ff" fontSize="13" fontWeight="700" letterSpacing="1.5">
        A2A · AGENT ↔ AGENT
      </text>
      <g>
        <line
          x1="120"
          y1="312"
          x2="200"
          y2="287"
          stroke="#9ec1ff"
          strokeOpacity="0.6"
          strokeWidth="2"
        />
        <line
          x1="120"
          y1="312"
          x2="190"
          y2="382"
          stroke="#9ec1ff"
          strokeOpacity="0.6"
          strokeWidth="2"
        />
        <line
          x1="200"
          y1="287"
          x2="190"
          y2="382"
          stroke="#9ec1ff"
          strokeOpacity="0.45"
          strokeWidth="2"
        />
        <circle
          cx="120"
          cy="312"
          r="20"
          fill="url(#ha-chipBlue)"
          stroke="#cfe0ff"
          strokeOpacity="0.7"
        />
        <circle
          cx="200"
          cy="287"
          r="20"
          fill="url(#ha-chipBlue)"
          stroke="#cfe0ff"
          strokeOpacity="0.7"
        />
        <circle
          cx="190"
          cy="382"
          r="20"
          fill="url(#ha-chipBlue)"
          stroke="#cfe0ff"
          strokeOpacity="0.7"
        />
        <text x="120" y="317" fill="#eaf1ff" fontSize="13" fontWeight="700" textAnchor="middle">
          A
        </text>
        <text x="200" y="292" fill="#eaf1ff" fontSize="13" fontWeight="700" textAnchor="middle">
          B
        </text>
        <text x="190" y="387" fill="#eaf1ff" fontSize="13" fontWeight="700" textAnchor="middle">
          C
        </text>
      </g>

      {/* MIDDLE — ACS shield */}
      <g filter="url(#ha-shadow)">
        <rect
          x="470"
          y="172"
          width="260"
          height="266"
          rx="28"
          fill="url(#ha-glass)"
          stroke="url(#ha-edge)"
          strokeWidth="1.5"
        />
      </g>
      <text
        x="600"
        y="216"
        fill="#e7d9ff"
        fontSize="13"
        fontWeight="700"
        letterSpacing="1.5"
        textAnchor="middle"
      >
        ACS · GOVERNANCE
      </text>
      <path
        d="M600 240 L662 262 V312 C662 348 634 372 600 386 C566 372 538 348 538 312 V262 Z"
        fill="#ffffff"
        fillOpacity="0.10"
        stroke="#d9c8ff"
        strokeOpacity="0.7"
        strokeWidth="1.5"
      />
      <path
        d="M576 312 l16 16 l34 -38"
        fill="none"
        stroke="#b07bff"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g fontSize="11" fontWeight="700" textAnchor="middle">
        <rect x="498" y="402" width="52" height="22" rx="11" fill="#1f7a4d" fillOpacity="0.5" />
        <text x="524" y="417" fill="#d7ffe9">
          allow
        </text>
        <rect x="556" y="402" width="48" height="22" rx="11" fill="#9a6a16" fillOpacity="0.55" />
        <text x="580" y="417" fill="#ffeccb">
          warn
        </text>
        <rect x="610" y="402" width="46" height="22" rx="11" fill="#9a2b2b" fillOpacity="0.55" />
        <text x="633" y="417" fill="#ffd9d9">
          deny
        </text>
        <rect x="662" y="402" width="62" height="22" rx="11" fill="#6a3fa6" fillOpacity="0.6" />
        <text x="693" y="417" fill="#efe2ff">
          escalate
        </text>
      </g>

      {/* RIGHT — AG-UI human interrupt */}
      <g filter="url(#ha-shadow)">
        <rect
          x="906"
          y="190"
          width="230"
          height="230"
          rx="26"
          fill="url(#ha-glass)"
          stroke="url(#ha-edge)"
          strokeWidth="1.5"
        />
      </g>
      <text
        x="1021"
        y="226"
        fill="#ffe6d2"
        fontSize="13"
        fontWeight="700"
        letterSpacing="1.5"
        textAnchor="middle"
      >
        AG-UI · AGENT ↔ HUMAN
      </text>
      <circle
        cx="1021"
        cy="274"
        r="17"
        fill="url(#ha-chipAmber)"
        stroke="#ffd9b0"
        strokeOpacity="0.8"
      />
      <path
        d="M998 314 a23 18 0 0 1 46 0 Z"
        fill="url(#ha-chipAmber)"
        stroke="#ffd9b0"
        strokeOpacity="0.8"
      />
      <g filter="url(#ha-blur8)" opacity="0.5">
        <rect x="936" y="334" width="170" height="64" rx="14" fill="#ffffff" fillOpacity="0.18" />
      </g>
      <rect
        x="936"
        y="334"
        width="170"
        height="64"
        rx="14"
        fill="#ffffff"
        fillOpacity="0.10"
        stroke="#ffe6d2"
        strokeOpacity="0.5"
      />
      <text x="950" y="358" fill="#fff0e2" fontSize="11" fontWeight="600">
        interrupt · confirmation
      </text>
      <rect x="950" y="366" width="64" height="22" rx="11" fill="#1f7a4d" fillOpacity="0.6" />
      <text x="982" y="381" fill="#d7ffe9" fontSize="11" fontWeight="700" textAnchor="middle">
        Approve
      </text>
      <rect x="1022" y="366" width="50" height="22" rx="11" fill="#9a2b2b" fillOpacity="0.6" />
      <text x="1047" y="381" fill="#ffd9d9" fontSize="11" fontWeight="700" textAnchor="middle">
        Deny
      </text>

      <text x="600" y="476" fill="#94a3b8" fontSize="13" textAnchor="middle" fontWeight="500">
        A2A &amp; MCP carry the bytes · ACS decides · AG-UI brings in the human
      </text>
    </svg>
  );
}
