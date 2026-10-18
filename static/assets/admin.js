(() => {
  'use strict';
  const $ = q => document.querySelector(q);
  const $$ = q => [...document.querySelectorAll(q)];
  const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = p => '₹' + (p/100).toLocaleString('en-IN',{maximumFractionDigits:2});
  const art = {Bats:'bat',Gloves:'gloves',Pads:'pads',Helmets:'helmet',Balls:'ball',Accessories:'accessories'};
  const artFor = p => p.image_url || '/assets/'+(art[p.category]||'accessories')+'.svg';
  let csrf = '';
  let products = [];
  let orders = [];
  let config = {demo_mode:true};
  const api = async (path, options = {}) => {
    const method = options.method || 'GET';
    const res = await fetch(path,{credentials:'same-origin', ...options,headers:{
      'Content-Type':'application/json',...(method === 'GET' ? {} : {'X-CSRF-Token':csrf}),...(options.headers || {})
    }});
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {let msg = data.detail || 'Something went wrong';if(Array.isArray(msg))msg=msg.map(x=>x.msg).join('; ');throw Error(String(msg));}
    return data;
  };
  function toast(message){const el=$('#adminToast');el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),3400);}
  function authScreen(){csrf='';$('#loginScreen').hidden=false;$('#adminApp').hidden=true;}
  function dashScreen(){$('#loginScreen').hidden=true;$('#adminApp').hidden=false;}
  function setTab(tab){$$('[data-tab]').forEach(el=>el.classList.toggle('active',el.dataset.tab===tab));$$('.admin-tab').forEach(el=>el.hidden=el.id!==`tab-${tab}`);$('#screenTitle').textContent={overview:'STORE OVERVIEW',orders:'ORDER MANAGEMENT',products:'PRODUCT INVENTORY'}[tab]||'STORE OVERVIEW';window.scrollTo({top:0,behavior:'smooth'});}
  const badge = (state) => `<span class="status ${escape(state)}">${escape(state.toUpperCase().replace('_',' '))}</span>`;
  const date = val => new Date(val).toLocaleString('en-IN',{dateStyle:'medium',timeStyle:'short'});
  function orderTable(items){return items.length ? `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>ORDER</th><th>CUSTOMER</th><th>AMOUNT</th><th>PAYMENT</th><th>FULFILMENT</th><th></th></tr></thead><tbody>${items.map(o=>`<tr><td><strong>${escape(o.reference)}</strong><small>${date(o.created_at)}</small></td><td><strong>${escape(o.customer_name)}</strong><small>${escape(o.email)}</small></td><td><strong>${money(o.total_paise)}</strong></td><td>${badge(o.payment_status)}</td><td>${badge(o.fulfillment_status)}</td><td><button data-order="${escape(o.reference)}">VIEW ↗</button></td></tr>`).join('')}</tbody></table></div>` : '<p class="admin-tips">No orders yet. New checkouts will appear here.</p>'}
  function renderOverview(){
    $('#statOrders').textContent=String(orders.length);
    const paid=orders.filter(o=>o.payment_status==='captured');
    $('#statPaid').textContent=String(paid.length);
    $('#statRevenue').textContent=money(paid.reduce((s,o)=>s+o.total_paise,0));
    $('#statLow').textContent=String(products.filter(p=>p.active&&p.stock<=5).length);
    $('#recentOrders').innerHTML=orderTable(orders.slice(0,5));
  }
  function renderOrders(){const term=$('#orderSearch').value.trim().toLowerCase();$('#ordersList').innerHTML=orderTable(orders.filter(o=>(o.reference+' '+o.customer_name+' '+o.email+' '+o.phone).toLowerCase().includes(term)));}
  function showOrder(reference){
    const o=orders.find(v=>v.reference===reference);if(!o)return;
    $('#orderDetail').hidden=false;
    $('#orderDetail').innerHTML=`<h3>${escape(o.reference)}</h3><div class="order-detail-grid"><section><h4>CUSTOMER & DELIVERY</h4><p><b>${escape(o.customer_name)}</b><br>${escape(o.email)}<br>${escape(o.phone)}</p><p>${escape(o.address)}<br>${escape(o.city)}, ${escape(o.state)} ${escape(o.pincode)}</p><p>Notes: ${escape(o.notes||'None')}</p></section><section><h4>ORDER DETAILS</h4>${o.items.map(i=>`<p>${escape(i.product_name)} × ${i.quantity} · ${money(i.unit_paise*i.quantity)}</p>`).join('')}<hr><p>Subtotal: ${money(o.subtotal_paise)}</p><p>Shipping: ${money(o.shipping_paise)}</p><p><b>Total: ${money(o.total_paise)}</b></p><p>Payment: ${badge(o.payment_status)}</p><p>Fulfilment: ${badge(o.fulfillment_status)}</p><p>Provider order: ${escape(o.razorpay_order_id||'—')}</p></section></div><div class="order-control"><label>FULFILMENT STATUS<select id="newFulfillment"><option value="new">New</option><option value="processing">Processing</option><option value="shipped">Shipped</option><option value="delivered">Delivered</option><option value="cancelled">Cancelled</option></select></label><button class="small-dark-btn" id="saveFulfillment">UPDATE STATUS ↗</button></div><p class="order-warning">Only captured payments can move to processing/shipped/delivered. Paid orders must go through a separate refund workflow before cancellation.</p>`;
    $('#newFulfillment').value=o.fulfillment_status;
    $('#saveFulfillment').addEventListener('click',async()=>{
      const status=$('#newFulfillment').value;
      if(status==='cancelled'&&!confirm('Cancel this unpaid order? This releases its reserved stock.'))return;
      try{await api(`/api/admin/orders/${encodeURIComponent(reference)}/fulfillment`,{method:'PATCH',body:JSON.stringify({fulfillment_status:status})});toast('Order updated');await refresh();showOrder(reference);}catch(err){toast(err.message);}
    });
    $('#orderDetail').scrollIntoView({behavior:'smooth',block:'start'});
  }
  function renderProducts(){
    const term=$('#productSearch').value.trim().toLowerCase();
    const found=products.filter(p=>(p.name+' '+p.sku+' '+p.category).toLowerCase().includes(term));
    $('#productsList').innerHTML=found.length?`<div class="data-table-wrap"><table class="data-table"><thead><tr><th>PRODUCT</th><th>SKU / CATEGORY</th><th>PRICE</th><th>STOCK</th><th>STATUS</th><th></th></tr></thead><tbody>${found.map(p=>`<tr><td><div class="data-product"><img src="${escape(artFor(p))}" alt=""><div><strong>${escape(p.name)}</strong>${p.sample?'<small>SAMPLE</small>':''}</div></div></td><td><strong>${escape(p.sku)}</strong><small>${escape(p.category)}</small></td><td>${money(p.price_paise)}</td><td><strong>${p.stock}</strong></td><td>${badge(p.active?'captured':'cancelled')}</td><td><button data-edit="${p.id}">EDIT ↗</button></td></tr>`).join('')}</tbody></table></div>`:'<p>No products match this search.</p>';
  }
  function editProduct(id){
    const p=products.find(v=>v.id===id);
    $('#productForm').reset();const f=$('#productForm');
    f.elements.product_id.value=p?.id||'';
    const keys=['sku','name','category','description','stock','image_url'];
    for(const k of keys)if(p)f.elements[k].value=p[k]??'';
    f.elements.price_rupees.value=p?(p.price_paise/100).toFixed(2):'';
    f.elements.compare_rupees.value=p?.compare_at_paise?(p.compare_at_paise/100).toFixed(2):'';
    f.elements.featured.checked=!!p?.featured;
    f.elements.active.checked=p?p.active:true;
    f.elements.sample.checked=!!p?.sample;
    $('#editTitle').textContent=p?'EDIT PRODUCT':'ADD PRODUCT';$('#productError').hidden=true;
    $('#editPanel').hidden=false;$('#editPanel').scrollIntoView({behavior:'smooth'});
  }
  async function saveProduct(event){
    event.preventDefault();const f=event.currentTarget;const data=new FormData(f);
    const id=data.get('product_id');
    const payload={sku:String(data.get('sku')).trim(),name:String(data.get('name')).trim(),category:String(data.get('category')),
      description:String(data.get('description')||'').trim(),price_paise:Math.round(Number(data.get('price_rupees'))*100),
      compare_at_paise:data.get('compare_rupees')?Math.round(Number(data.get('compare_rupees'))*100):null,
      stock:Number(data.get('stock')),image_url:String(data.get('image_url')||'').trim(),
      featured:data.has('featured'),active:data.has('active'),sample:data.has('sample')};
    const error=$('#productError');error.hidden=true;
    const btn=$('#saveProductBtn');btn.disabled=true;
    try{await api(id?`/api/admin/products/${id}`:'/api/admin/products', {method:id?'PUT':'POST',body:JSON.stringify(payload)});$('#editPanel').hidden=true;toast('Product saved');await refresh();setTab('products');}
    catch(err){error.textContent=err.message;error.hidden=false;}
    finally{btn.disabled=false;}
  }
  async function refresh(){
    try{const [p,o]=await Promise.all([api('/api/admin/products'),api('/api/admin/orders')]);products=p.products;orders=o.orders;renderOverview();renderOrders();renderProducts();}
    catch(err){toast(err.message);if(String(err.message).toLowerCase().includes('login')||String(err.message).includes('expired'))authScreen();}
  }
  async function bootstrap(){
    config=await api('/api/config').catch(()=>({demo_mode:true}));
    if(config.demo_mode)$('#adminDemoNotice').hidden=false;
    try{const session=await api('/api/admin/session');csrf=session.csrf;dashScreen();await refresh();}
    catch{authScreen();}
  }
  $('#loginForm').addEventListener('submit',async e=>{
    e.preventDefault();const data=Object.fromEntries(new FormData(e.currentTarget).entries());
    const error=$('#loginError');error.hidden=true;
    const btn=e.currentTarget.querySelector('button');btn.disabled=true;
    try{const response=await api('/api/admin/login',{method:'POST',body:JSON.stringify(data)});csrf=response.csrf;dashScreen();await refresh();}
    catch(err){error.textContent=err.message;error.hidden=false;}
    finally{btn.disabled=false;}
  });
  $('#logoutBtn').addEventListener('click',async()=>{try{await api('/api/admin/logout',{method:'POST'});}catch{}authScreen();});
  $$('[data-tab]').forEach(b=>b.addEventListener('click',()=>setTab(b.dataset.tab)));
  $('#refreshBtn').addEventListener('click',async()=>{await refresh();toast('Dashboard refreshed');});
  $('#recentOrders').addEventListener('click',e=>{const b=e.target.closest('[data-order]');if(b){setTab('orders');showOrder(b.dataset.order);}});
  $('#ordersList').addEventListener('click',e=>{const b=e.target.closest('[data-order]');if(b)showOrder(b.dataset.order);});
  $('#productsList').addEventListener('click',e=>{const b=e.target.closest('[data-edit]');if(b)editProduct(Number(b.dataset.edit));});
  $('#newProductBtn').addEventListener('click',()=>editProduct(null));
  $('#cancelEdit').addEventListener('click',()=>$('#editPanel').hidden=true);
  $('#productForm').addEventListener('submit',saveProduct);
  $('#productSearch').addEventListener('input',renderProducts);
  $('#orderSearch').addEventListener('input',renderOrders);
  bootstrap();
})();
