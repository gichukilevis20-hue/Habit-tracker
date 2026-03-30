document.addEventListener('DOMContentLoaded', function() {
  let ticking = false;
  
  function updateNavbar() {
    const navbar = document.querySelector('.app-navbar');
    const backdrop = document.querySelector('.site-backdrop');
    
    if (navbar) {
      if (window.scrollY > 50) {
        navbar.classList.add('scrolled');
      } else {
        navbar.classList.remove('scrolled');
      }
    }
    
    if (backdrop) {
      backdrop.style.transform = `translateY(${window.scrollY * 0.5}px)`;
    }
    
    ticking = false;
  }
  
  window.addEventListener('scroll', function() {
    if (!ticking) {
      requestAnimationFrame(updateNavbar);
      ticking = true;
    }
  });
  
  // Card hover enhancements
  const cards = document.querySelectorAll('.habit-card, .stat-card, .panel-card');
  cards.forEach(card => {
    card.addEventListener('mouseenter', function() {
      this.style.transform = 'translateY(-6px) scale(1.02)';
    });
    card.addEventListener('mouseleave', function() {
      this.style.transform = 'translateY(0) scale(1)';
    });
  });
});
