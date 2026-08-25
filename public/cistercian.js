// SVG paths for digits 1-9 in the top-right (units) quadrant
const CISTERCIAN_PATHS = {
    1: "M 15 0 L 30 0",
    2: "M 15 20 L 30 20",
    3: "M 15 0 L 30 20",
    4: "M 15 20 L 30 0",
    5: "M 15 0 L 30 0 L 15 20",
    6: "M 30 0 L 30 20",
    7: "M 15 0 L 30 0 L 30 20",
    8: "M 15 20 L 30 20 L 30 0",
    9: "M 15 0 L 30 0 L 30 20 L 15 20"
};

function generateCistercianSvg(numStr) {
    if (numStr === "0") {
        return createSvg([staffPath()]);
    }
    
    // Chunk into up to 4 digits from right-to-left
    let chunks = [];
    let s = numStr;
    while (s.length > 0) {
        chunks.push(s.slice(-4));
        s = s.slice(0, -4);
    }
    chunks.reverse(); // Now it's left-to-right chunks
    
    return chunks.map(chunk => {
        let val = parseInt(chunk, 10);
        if (val === 0) return createSvg([staffPath()]);
        
        let elements = [staffPath()];
        
        let units = val % 10;
        let tens = Math.floor(val / 10) % 10;
        let hundreds = Math.floor(val / 100) % 10;
        let thousands = Math.floor(val / 1000) % 10;
        
        if (units > 0) elements.push(`<path d="${CISTERCIAN_PATHS[units]}" />`);
        if (tens > 0) elements.push(`<g transform="translate(30, 0) scale(-1, 1)"><path d="${CISTERCIAN_PATHS[tens]}" /></g>`);
        if (hundreds > 0) elements.push(`<g transform="translate(0, 60) scale(1, -1)"><path d="${CISTERCIAN_PATHS[hundreds]}" /></g>`);
        if (thousands > 0) elements.push(`<g transform="translate(30, 60) scale(-1, -1)"><path d="${CISTERCIAN_PATHS[thousands]}" /></g>`);
        
        return createSvg(elements, chunk);
    }).join("");
}

function staffPath() {
    return `<line x1="15" y1="0" x2="15" y2="60" />`;
}

function createSvg(elements, valStr) {
    // Add aria-label for accessibility
    const aria = valStr ? `aria-label="${valStr}" role="img"` : `aria-hidden="true"`;
    return `<svg class="cistercian" viewBox="-2 -2 34 64" ${aria}>${elements.join("")}</svg>`;
}

// Global function to parse and render markers in a container
window.renderCistercianMarkers = function(container) {
    let html = container.innerHTML;
    // Match ‹1984›
    html = html.replace(/‹(\d+)›/g, (match, p1) => {
        return generateCistercianSvg(p1);
    });
    container.innerHTML = html;
};
