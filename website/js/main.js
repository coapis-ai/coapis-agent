/**
 * CoApis Official Website
 * Main JavaScript
 */

// ── Navbar scroll effect ─────────────────────────
const navbar = document.getElementById('navbar');

window.addEventListener('scroll', () => {
    if (window.scrollY > 50) {
        navbar.classList.add('scrolled');
    } else {
        navbar.classList.remove('scrolled');
    }
});

// ── Mobile menu toggle ───────────────────────────
function toggleMenu() {
    const navLinks = document.getElementById('navLinks');
    navLinks.classList.toggle('active');
}

// Close mobile menu when clicking a link
document.querySelectorAll('.nav-links a').forEach(link => {
    link.addEventListener('click', () => {
        document.getElementById('navLinks').classList.remove('active');
    });
});

// ── Scroll animations ────────────────────────────
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('visible');
            observer.unobserve(entry.target);
        }
    });
}, observerOptions);

document.querySelectorAll('.animate-on-scroll').forEach(el => {
    observer.observe(el);
});

// ── Smooth scroll for anchor links ───────────────
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        const href = this.getAttribute('href');
        if (href === '#') return;

        e.preventDefault();
        const target = document.querySelector(href);
        if (target) {
            const offset = 80; // navbar height
            const targetPosition = target.getBoundingClientRect().top + window.pageYOffset - offset;
            window.scrollTo({
                top: targetPosition,
                behavior: 'smooth'
            });
        }
    });
});

// ── Contact form handling ────────────────────────
function handleSubmit(e) {
    e.preventDefault();

    const form = e.target;
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);

    // Show success message (in production, send to backend)
    const btn = form.querySelector('button[type="submit"]');
    const originalText = btn.textContent;

    btn.textContent = '发送中...';
    btn.disabled = true;

    // Simulate API call
    setTimeout(() => {
        btn.textContent = '✓ 发送成功';
        btn.style.background = '#27ae60';

        // Log data (in production, send to your backend)
        console.log('Contact form submitted:', data);

        // Reset form after delay
        setTimeout(() => {
            form.reset();
            btn.textContent = originalText;
            btn.style.background = '';
            btn.disabled = false;
        }, 2000);
    }, 1000);
}

// ── Active nav link highlight ────────────────────
const sections = document.querySelectorAll('section[id]');

function highlightNav() {
    const scrollY = window.pageYOffset;

    sections.forEach(section => {
        const sectionHeight = section.offsetHeight;
        const sectionTop = section.offsetTop - 100;
        const sectionId = section.getAttribute('id');
        const navLink = document.querySelector(`.nav-links a[href="#${sectionId}"]`);

        if (navLink) {
            if (scrollY > sectionTop && scrollY <= sectionTop + sectionHeight) {
                navLink.style.color = 'var(--primary)';
            } else {
                navLink.style.color = '';
            }
        }
    });
}

window.addEventListener('scroll', highlightNav);

// ── Print page detection ─────────────────────────
if (window.matchMedia('print').matches) {
    document.body.classList.add('printing');
}

// ── Performance: lazy load images ────────────────
if ('loading' in HTMLImageElement.prototype) {
    document.querySelectorAll('img[loading="lazy"]').forEach(img => {
        img.src = img.dataset.src;
    });
} else {
    // Fallback for browsers that don't support lazy loading
    const script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/lazysizes/5.3.2/lazysizes.min.js';
    document.body.appendChild(script);
}

// ── Page load animation ──────────────────────────
window.addEventListener('load', () => {
    document.body.style.opacity = '1';
});

console.log('%c🦀 CoApis', 'font-size: 24px; font-weight: bold; color: #ff6b35;');
console.log('%c多用户服务端 AI 智能体平台', 'font-size: 14px; color: #666;');
