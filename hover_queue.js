document.addEventListener('DOMContentLoaded', () => {
    const sidebar = document.querySelector('.queue-sidebar');
    if (!sidebar) return;
    
    // Distance from the right edge (in pixels) to trigger the sidebar
    const TRIGGER_WIDTH = 80;

    document.addEventListener('mousemove', (e) => {
        // Disable hover on mobile, let the toggle button handle it
        if (window.innerWidth <= 768) return; 
        
        const windowWidth = window.innerWidth;
        
        // Check if mouse is near the right edge
        const isEdgeHover = (windowWidth - e.clientX) <= TRIGGER_WIDTH;
        
        if (isEdgeHover) {
            sidebar.classList.add('show');
        } else {
            // If the sidebar is currently shown, check if the mouse is over it
            if (sidebar.classList.contains('show')) {
                const rect = sidebar.getBoundingClientRect();
                const isSidebarHover = e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom;
                if (!isSidebarHover) sidebar.classList.remove('show');
            }
        }
    });
});