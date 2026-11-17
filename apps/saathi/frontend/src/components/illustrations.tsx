// Hand-drawn SVG illustrations (inline, so they work under the strict Content-Security-Policy).

/** Village scene: a helper shows an elderly woman the schemes she qualifies for on a phone. */
export function HeroIllustration({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 480 400" className={className} role="img" aria-label="A helper showing a woman the welfare schemes she qualifies for">
      {/* sun and hills */}
      <circle cx="372" cy="96" r="54" fill="#fcc155" opacity="0.9" />
      <circle cx="372" cy="96" r="78" fill="#fcc155" opacity="0.18" />
      <path d="M0 300 C80 240 150 250 230 285 S380 250 480 270 V400 H0Z" fill="#2a947f" opacity="0.55" />
      <path d="M0 330 C110 290 200 300 290 320 S420 300 480 310 V400 H0Z" fill="#1c7867" />
      <path d="M0 362 C120 340 260 350 480 344 V400 H0Z" fill="#164e45" />

      {/* house */}
      <g transform="translate(46 228)">
        <rect x="6" y="34" width="72" height="52" rx="3" fill="#feebc7" />
        <path d="M0 38 L42 4 L84 38Z" fill="#d96706" />
        <rect x="32" y="56" width="18" height="30" rx="2" fill="#186154" />
        <rect x="14" y="48" width="12" height="12" rx="2" fill="#7dcdb9" />
        <rect x="58" y="48" width="12" height="12" rx="2" fill="#7dcdb9" />
      </g>
      {/* tree */}
      <g transform="translate(410 214)">
        <rect x="14" y="44" width="8" height="54" rx="3" fill="#7a4a2a" />
        <circle cx="18" cy="34" r="26" fill="#4bb09a" />
        <circle cx="4" cy="46" r="16" fill="#2a947f" />
        <circle cx="32" cy="48" r="15" fill="#2a947f" />
      </g>

      {/* ground shadow */}
      <ellipse cx="236" cy="362" rx="120" ry="10" fill="#0a2622" opacity="0.25" />

      {/* elderly woman in a saree */}
      <g>
        <path d="M150 238 C142 270 136 320 132 356 H214 C210 320 204 270 196 238 Z" fill="#f58b0b" />
        <path d="M150 238 C160 262 176 300 214 356 H196 C176 316 160 280 150 252 Z" fill="#d96706" />
        <path d="M152 236 C160 228 186 228 194 236 L198 262 L148 262 Z" fill="#fbab2b" />
        <circle cx="173" cy="212" r="19" fill="#b97a4f" />
        <path d="M152 214 C150 186 196 182 196 214 C192 200 156 198 152 214 Z" fill="#e4e1da" />
        <path d="M150 216 C146 190 168 180 186 186 C200 192 202 212 198 238 L192 236 C194 214 188 198 174 196 C160 196 154 210 156 236 L150 238 Z" fill="#fbab2b" />
        <circle cx="166" cy="214" r="1.8" fill="#3b2416" />
        <circle cx="180" cy="214" r="1.8" fill="#3b2416" />
        <path d="M167 223 Q173 228 179 223" stroke="#3b2416" strokeWidth="1.8" fill="none" strokeLinecap="round" />
        {/* hand reaching towards the phone */}
        <path d="M194 262 C206 266 216 266 226 262" stroke="#b97a4f" strokeWidth="9" strokeLinecap="round" fill="none" />
      </g>

      {/* helper with a phone */}
      <g>
        <rect x="266" y="318" width="14" height="40" rx="5" fill="#133f39" />
        <rect x="286" y="318" width="14" height="40" rx="5" fill="#133f39" />
        <path d="M258 236 C258 222 308 222 308 236 L312 326 H254 Z" fill="#186154" />
        <path d="M276 226 L283 244 L290 226" fill="#d7f2ea" />
        <circle cx="283" cy="200" r="19" fill="#9c6640" />
        <path d="M264 198 C262 176 304 172 303 198 C298 188 270 186 264 198 Z" fill="#1f1611" />
        <circle cx="276" cy="203" r="1.8" fill="#1f1611" />
        <circle cx="290" cy="203" r="1.8" fill="#1f1611" />
        <path d="M277 211 Q283 216 289 211" stroke="#1f1611" strokeWidth="1.8" fill="none" strokeLinecap="round" />
        {/* arm holding phone */}
        <path d="M262 250 C252 262 246 268 238 268" stroke="#186154" strokeWidth="12" strokeLinecap="round" fill="none" />
        <rect x="222" y="246" width="22" height="36" rx="4" fill="#0a2622" transform="rotate(-12 233 264)" />
        <rect x="225" y="250" width="16" height="26" rx="2" fill="#7dcdb9" transform="rotate(-12 233 264)" />
      </g>

      {/* floating scheme card */}
      <g className="animate-float">
        <rect x="170" y="88" width="132" height="86" rx="14" fill="#ffffff" />
        <rect x="170" y="88" width="132" height="86" rx="14" fill="none" stroke="#d7f2ea" strokeWidth="2" />
        <circle cx="196" cy="116" r="13" fill="#2a947f" />
        <path d="M189 116 l5 5 l9 -10" stroke="#fff" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="216" y="108" width="68" height="7" rx="3.5" fill="#164e45" />
        <rect x="216" y="120" width="48" height="6" rx="3" fill="#afe3d5" />
        <rect x="186" y="142" width="98" height="6" rx="3" fill="#e7e5e4" />
        <rect x="186" y="154" width="72" height="6" rx="3" fill="#e7e5e4" />
        <path d="M228 174 L236 186 L244 174 Z" fill="#ffffff" />
      </g>

      {/* rupee coin and sparkles */}
      <g className="animate-float [animation-delay:1.5s]">
        <circle cx="332" cy="172" r="22" fill="#fbab2b" />
        <circle cx="332" cy="172" r="16" fill="none" stroke="#feebc7" strokeWidth="2" />
        <text x="332" y="180" textAnchor="middle" fontSize="22" fontWeight="700" fill="#fff8eb" fontFamily="sans-serif">₹</text>
      </g>
      <path d="M128 120 l3 7 7 3 -7 3 -3 7 -3 -7 -7 -3 7 -3z" fill="#fff8eb" />
      <path d="M326 236 l2 5 5 2 -5 2 -2 5 -2 -5 -5 -2 5 -2z" fill="#fff8eb" opacity="0.8" />
      <path d="M118 176 l2 4 4 2 -4 2 -2 4 -2 -4 -4 -2 4 -2z" fill="#fcc155" />
    </svg>
  );
}
