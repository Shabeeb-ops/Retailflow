
function toggleSidebar(){const sidebar=document.getElementById('sidebar');sidebar.classList.toggle('collapsed');document.querySelector('.toggle-btn').setAttribute('aria-expanded',String(!sidebar.classList.contains('collapsed')))}
const search=document.querySelector('.search-box input');search.setAttribute('aria-label','Search navigation');search.addEventListener('input',function(){const query=this.value.trim().toLowerCase();document.querySelectorAll('.menu-item').forEach(item=>{item.hidden=!item.textContent.toLowerCase().includes(query)})});
