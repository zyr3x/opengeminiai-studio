document.addEventListener('DOMContentLoaded', function() {
    const htmlElement = document.documentElement;
    const darkModeToggle = document.getElementById('darkModeToggle');
    const darkModeIcon = document.getElementById('darkModeIcon');
    const navLinks = document.querySelectorAll('.nav-link');
    const contentSections = document.querySelectorAll('.content-section');
    const navbarCollapse = document.getElementById('navbarNav');
    const mainContent = document.querySelector('.main-content');
    const body = document.querySelector('body');
    // Function to set the theme
    function setTheme(theme) {
        htmlElement.setAttribute('data-bs-theme', theme);
        localStorage.setItem('theme', theme);
        if (darkModeToggle) { // Ensure toggle exists before trying to set its state
            darkModeToggle.checked = (theme === 'dark');
        }
        if (darkModeIcon) { // Ensure icon exists before trying to set its content
            darkModeIcon.textContent = (theme === 'dark') ? 'dark_mode' : 'light_mode';
        }
    }

    // Function to show/hide content sections based on hash
    function showSectionBasedOnHash() {
        let hash = window.location.hash || '#chat';
        let sectionId = hash.substring(1);

        // Hide all sections
        contentSections.forEach(function(section) {
            section.style.display = 'none';
        });

        // Show the target section
        let targetSection = document.getElementById(sectionId);
        if (targetSection) {
            targetSection.style.display = 'block';
        } else {
            // Fallback to chat if hash is invalid
            const chatSection = document.getElementById('chat');
            if (chatSection) {
                chatSection.style.display = 'block';
            }
            hash = '#chat';
        }

        if (mainContent) {
            if (hash === '#chat') {
                body.classList.add('chat');
                mainContent.classList.remove('container');
                mainContent.classList.add('container-fluid');
            } else {
                body.classList.remove('chat');
                mainContent.classList.remove('container-fluid');
                mainContent.classList.add('container');
            }
        }

        // Update active link in navbar
        navLinks.forEach(function(link) {
            if (link.getAttribute('href') === hash) {
                link.classList.add('active');
                link.setAttribute('aria-current', 'page');
            } else {
                link.classList.remove('active');
                link.removeAttribute('aria-current');
            }
        });
    }


    // --- Initializations ---

    // 1. Check for saved theme preference or system preference
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
        setTheme(savedTheme);
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        setTheme('dark');
    } else {
        setTheme('light');
    }

    // 2. Display the correct content section on load
    showSectionBasedOnHash();

    // --- Event Listeners ---

    // 1. Toggle theme on switch change
    if (darkModeToggle) { // Only add listener if toggle element exists
        darkModeToggle.addEventListener('change', function() {
            if (this.checked) {
                setTheme('dark');
            } else {
                setTheme('light');
            }
        });
    }

    // 2. Handle navigation to content sections
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const targetId = this.getAttribute('href');

            // Update URL hash without page reload, which will trigger hashchange event
            history.pushState(null, '', targetId);
            showSectionBasedOnHash(); // Manually call to update UI immediately

            // Close navbar toggler on link click for small screens
            if (navbarCollapse) {
                const bsCollapse = bootstrap.Collapse.getInstance(navbarCollapse);
                if (bsCollapse && navbarCollapse.classList.contains('show')) {
                    bsCollapse.hide();
                }
            }
        });
    });

    // 3. Re-run section display logic on hash change (e.g., if user navigates using browser back/forward)
    window.addEventListener('hashchange', showSectionBasedOnHash);
});
