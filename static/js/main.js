document.addEventListener('DOMContentLoaded', function() {
    function showSectionBasedOnHash() {
        var hash = window.location.hash || '#home';
        var sectionId = hash.substring(1);

        // Hide all sections
        document.querySelectorAll('.content-section').forEach(function(section) {
            section.style.display = 'none';
        });

        // Show the target section
        var targetSection = document.getElementById(sectionId);
        if (targetSection) {
            targetSection.style.display = 'block';
        } else {
            // Fallback to home if hash is invalid
            document.getElementById('home').style.display = 'block';
            hash = '#home';
        }

        // Update active link in navbar
        document.querySelectorAll('.navbar-nav .nav-link').forEach(function(link) {
            if (link.getAttribute('href') === hash) {
                link.classList.add('active');
                link.setAttribute('aria-current', 'page');
            } else {
                link.classList.remove('active');
                link.removeAttribute('aria-current');
            }
        });
    }

    // Run on page load
    showSectionBasedOnHash();

    // Run on hash change
    window.addEventListener('hashchange', showSectionBasedOnHash);

    // Close navbar toggler on link click for small screens
    document.querySelectorAll('.navbar-nav .nav-link').forEach(function(link) {
        link.addEventListener('click', function() {
            var navbarCollapse = document.getElementById('navbarNav');
            // Check if the navbar is actually collapsed (i.e., toggler is visible)
            var bsCollapse = bootstrap.Collapse.getInstance(navbarCollapse);
            if (bsCollapse && navbarCollapse.classList.contains('show')) {
                bsCollapse.hide();
            }
        });
    });
});
