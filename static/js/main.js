document.addEventListener("DOMContentLoaded",()=>{
  const token=document.querySelector('meta[name="csrf-token"]')?.content;
  document.querySelectorAll("form").forEach(form=>{
    if(token && form.method.toLowerCase()==="post" && !form.querySelector('input[name="csrf_token"]')){
      const input=document.createElement("input");
      input.type="hidden"; input.name="csrf_token"; input.value=token;
      form.appendChild(input);
    }
  });
  const els=document.querySelectorAll(".reveal");
  if(window.matchMedia("(prefers-reduced-motion: reduce)").matches){
    els.forEach(e=>e.classList.add("visible"));
  } else {
    const io=new IntersectionObserver(es=>es.forEach(e=>{
      if(e.isIntersecting){e.target.classList.add("visible");io.unobserve(e.target)}
    }),{threshold:.12});
    els.forEach(e=>io.observe(e));
  }
  document.querySelectorAll("[data-confirm]").forEach(b=>b.addEventListener("click",e=>{
    if(!confirm(b.dataset.confirm))e.preventDefault();
  }));
});