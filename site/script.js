/* ============================================
   FAMLIES Website - JavaScript
   ============================================ */

// Note: YAML parsing is handled by the js-yaml library (loaded via CDN in events.html)
// This allows us to support full YAML syntax without a custom parser

// Load and render events
async function loadEvents() {
    const container = document.getElementById('events-container');
    if (!container) return;

    try {
        const response = await fetch('config/events.yml');
        const yamlText = await response.text();
        const data = jsyaml.load(yamlText);
        const events = data.events || [];

        // Sort events in reverse chronological order (newest first)
        events.sort((a, b) => new Date(b.date) - new Date(a.date));

        const today = new Date();
        today.setHours(0, 0, 0, 0);

        container.innerHTML = '';
        events.forEach(event => {
            if (!event.date || !event.title) return;

            // Parse date correctly (YYYY-MM-DD format)
            const dateParts = event.date.split('-');
            const year = parseInt(dateParts[0]);
            const monthNum = parseInt(dateParts[1]) - 1;
            const day = parseInt(dateParts[2]);

            const dateObj = new Date(year, monthNum, day);
            const month = dateObj.toLocaleString('en-US', { month: 'short' }).toUpperCase();

            // Check if event is in the past
            const eventDateOnly = new Date(year, monthNum, day);
            const isPastEvent = eventDateOnly < today;
            const dateBarClass = isPastEvent ? 'event-date-past' : 'event-date';

            const speakersLabel = event.speakers && event.speakers.length > 1 ? 'Speakers' : 'Speaker';
            const speakersText = event.speakers && event.speakers.length > 0
                ? `<p class="event-speakers"><strong>${speakersLabel}:</strong> ${event.speakers.join(', ')}</p>`
                : '';

            const eventLinkHTML = event.event_link
                ? `<div class="event-actions"><a href="${event.event_link}" class="event-link" target="_blank">Register/Join →</a></div>`
                : '';

            const filesHTML = event.files && event.files.length > 0
                ? `<div class="event-files"><p class="event-files-label">Files:</p><ul class="event-files-list">${event.files.map(file => `<li><a href="${file.url}" target="_blank">${file.name}</a></li>`).join('')}</ul></div>`
                : '';

            const eventHTML = `<div class="event-card">
                <div class="${dateBarClass}">
                    <div class="event-month">${month}</div>
                    <div class="event-day">${day}</div>
                </div>
                <div class="event-content">
                    <h3>${event.title}</h3>
                    <p class="event-time">${event.time_range} | ${event.location}</p>
                    <p class="event-description">${event.description}</p>
                    ${speakersText}${eventLinkHTML}${filesHTML}
                </div>
            </div>`;
            container.innerHTML += eventHTML;
        });

        if (events.length === 0) {
            container.innerHTML = '<p style="color: var(--secondary-color);">No events scheduled.</p>';
        }
    } catch (error) {
        console.error('Error loading events:', error);
        container.innerHTML = '<p style="color: var(--secondary-color);">Unable to load events. Please check back soon.</p>';
    }
}

// Parse BibTeX format
function parseBibTeX(bibContent) {
    const entries = [];
    const bibRegex = /@(\w+)\s*{\s*([^,]+),\s*([\s\S]*?)(?=@\w+\s*{|$)/g;
    let match;

    while ((match = bibRegex.exec(bibContent)) !== null) {
        const type = match[1].toLowerCase();
        const key = match[2].trim();
        const fieldsText = match[3];

        const fields = {};
        const fieldRegex = /(\w+)\s*=\s*["{]([^"}]*)["}]/g;
        let fieldMatch;

        while ((fieldMatch = fieldRegex.exec(fieldsText)) !== null) {
            const fieldName = fieldMatch[1].toLowerCase();
            const fieldValue = fieldMatch[2].trim();
            fields[fieldName] = fieldValue;
        }

        entries.push({
            key: key,
            type: type,
            fields: fields
        });
    }

    return entries;
}

// Generate publication links (URL, DOI, arXiv)
function generatePublicationLinks(fields) {
    const links = [];

    if (fields.url) {
        const url = fields.url;
        const isArxiv = url.includes('arxiv.org');

        if (isArxiv) {
            // For arXiv URLs, add both abstract and PDF links
            const arxivMatch = url.match(/arxiv\.org\/abs\/(\d+\.\d+)/);
            if (arxivMatch) {
                const arxivId = arxivMatch[1];
                links.push({
                    text: 'arXiv Preprint',
                    url: url
                });
                links.push({
                    text: 'PDF',
                    url: `https://arxiv.org/pdf/${arxivId}.pdf`
                });
            }
        } else {
            links.push({
                text: 'View Paper',
                url: url
            });
        }
    } else if (fields.doi) {
        // Generate DOI link
        const doiUrl = fields.doi.startsWith('http') ? fields.doi : `https://doi.org/${fields.doi}`;
        links.push({
            text: 'DOI',
            url: doiUrl
        });
    }

    return links;
}

// Format author names
function formatAuthors(authorStr) {
    if (!authorStr) return '';
    return authorStr.split(' and ').map(a => a.trim()).join(', ');
}

// Create publication HTML element
function createPublicationElement(entry) {
    const { fields } = entry;

    const title = fields.title || 'Untitled';
    const authors = formatAuthors(fields.author || '');
    const year = fields.year || '';
    const journal = fields.journal || fields.booktitle || fields.institution || '';
    const abstract = fields.abstract || '';

    const links = generatePublicationLinks(fields);

    let metaText = '';
    if (journal && year) {
        metaText = `${journal}, ${year}`;
    } else if (journal) {
        metaText = journal;
    } else if (year) {
        metaText = year;
    }

    let linksHTML = '';
    if (links.length > 0) {
        linksHTML = '<div class="publication-links">' +
            links.map(link => `<a href="${link.url}" class="pub-link" target="_blank">${link.text}</a>`).join('') +
            '</div>';
    }

    const html = `
        <div class="publication-item">
            <div class="publication-header">
                <h3>${title}</h3>
                ${metaText ? `<p class="publication-meta">${metaText}</p>` : ''}
            </div>
            <div class="publication-details">
                ${authors ? `<p class="publication-authors"><strong>Authors:</strong> ${authors}</p>` : ''}
                ${abstract ? `<p class="publication-abstract">${abstract}</p>` : ''}
                ${linksHTML}
            </div>
        </div>
    `;

    return html;
}

// Load and render publications from BibTeX files
async function loadPublications() {
    try {
        // Load FAWN publications
        const fawnResponse = await fetch('config/fawns.bib');
        const fawnText = await fawnResponse.text();
        const fawnEntries = parseBibTeX(fawnText);

        // Load related publications
        const relatedResponse = await fetch('config/related.bib');
        const relatedText = await relatedResponse.text();
        const relatedEntries = parseBibTeX(relatedText);

        // Render FAWN publications
        const fawnContainer = document.querySelector('.fawn-publications-list');
        if (fawnContainer && fawnEntries.length > 0) {
            fawnContainer.innerHTML = fawnEntries.map(createPublicationElement).join('');
        }

        // Render related publications
        const relatedContainer = document.querySelector('.related-publications-list');
        if (relatedContainer && relatedEntries.length > 0) {
            relatedContainer.innerHTML = relatedEntries.map(createPublicationElement).join('');
        }
    } catch (error) {
        console.error('Error loading publications:', error);
    }
}

// Load events on page load if on events page
document.addEventListener('DOMContentLoaded', function() {
    loadEvents();
    loadPublications();

    // Active navigation link tracking
    const currentPage = window.location.pathname.split('/').pop() || 'index.html';
    const navLinks = document.querySelectorAll('.nav-link');

    navLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (href === currentPage || (currentPage === '' && href === 'index.html')) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
});

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        const href = this.getAttribute('href');
        if (href !== '#' && document.querySelector(href)) {
            e.preventDefault();
            document.querySelector(href).scrollIntoView({
                behavior: 'smooth'
            });
        }
    });
});

// Optional: Add scroll animation for elements
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -100px 0px'
};

const observer = new IntersectionObserver(function(entries) {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, observerOptions);

// Observe all content sections for fade-in animation
document.querySelectorAll('.content-section, .objective-card, .cta-card').forEach(el => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(20px)';
    el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
    observer.observe(el);
});
