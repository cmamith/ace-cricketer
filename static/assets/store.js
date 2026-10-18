(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const money = (paise) => '₹' + (paise / 100).toLocaleString('en-IN', {minimumFractionDigits: 0,maximumFractionDigits: 2});
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const art = {Bats:'bat',Gloves:'gloves',Pads:'pads',Helmets:'helmet',Balls:'ball',Accessories:'accessories'};
  const artFor = (product) => product.image_url || '/assets/' + (art[product.category] || 'accessories') + '.svg';
  const api = async (url, options = {}) => {
    const res = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      let detail = data.detail || 'Could not complete the request';
      if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join('; ');
      throw Error(String(detail));
    }
    return data;
  };
  let config = {demo_mode: true, payments_enabled: false, shipping_fee_paise:0, free_shipping_above_paise:0};
  let products = [];
  let filter = 'All';
  let search = '';
  let toastTimer = null;
  let drawerIsOpen = false;
  let activeDialog = null;
  let cart = {};
  try {
    const stored = JSON.parse(localStorage.getItem('ace_cart_v1') || '{}');
    if (stored && typeof stored === 'object' && !Array.isArray(stored)) cart = stored;
  } catch { cart = {}; }

  const saveCart = () => {
    localStorage.setItem('ace_cart_v1', JSON.stringify(cart));
    renderCart();
  };
  function toast(message) {
    const el = $('#toast'); el.textContent = message; el.classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 3300);
  }
  function allCartItems() {
    return Object.entries(cart).map(([key, qty]) => ({product:products.find(p => p.id === Number(key)),qty:Number(qty)}))
      .filter(v => v.product && v.qty > 0 && v.product.active);
  }
  function countCart() { return allCartItems().reduce((s,v) => s + v.qty, 0); }
  function shipping(subtotal) {
    return config.free_shipping_above_paise && subtotal >= config.free_shipping_above_paise ? 0 : config.shipping_fee_paise;
  }
  function renderProducts() {
    let list = products.filter(p => (filter === 'All' || p.category === filter) &&
       (p.name + ' ' + p.category + ' ' + p.description).toLowerCase().includes(search));
    const sort = $('#sortSelect').value;
    if (sort === 'price_asc') list.sort((a,b) => a.price_paise - b.price_paise);
    else if (sort === 'price_desc') list.sort((a,b) => b.price_paise - a.price_paise);
    else if (sort === 'name') list.sort((a,b) => a.name.localeCompare(b.name));
    else list.sort((a,b) => Number(b.featured) - Number(a.featured) || a.id - b.id);
    $('#productGrid').innerHTML = list.length ? list.map(p => {
      const discount = p.compare_at_paise > p.price_paise ? Math.round(100*(1-p.price_paise/p.compare_at_paise)) : 0;
      return `<article class="product-card"><div class="product-visual"><img src="${escape(artFor(p))}" alt="${escape(p.name)}" loading="lazy">${p.featured ? '<span class="product-badge">FEATURED</span>' : ''}${discount ? `<span class="product-discount">-${discount}%</span>` : ''}</div><div class="product-body"><small class="product-category">${escape(p.category)} / ${escape(p.sku)}</small><h3>${escape(p.name)}</h3><p class="product-desc">${escape(p.description)}</p><div class="product-price"><strong>${money(p.price_paise)}</strong>${p.compare_at_paise > p.price_paise ? `<del>${money(p.compare_at_paise)}</del>` : ''}</div><button class="add-btn" data-add="${p.id}" ${p.stock <= 0 ? 'disabled' : ''}>${p.stock > 0 ? 'ADD TO BAG' : 'OUT OF STOCK'} <span>↗</span></button></div></article>`;
    }).join('') : '<p class="empty-products">Nothing in this category yet. Try another filter.</p>';
    $('#productCount').textContent = `SHOWING ${list.length} OF ${products.length} ITEMS`;
  }
  function addItem(id) {
    const p = products.find(v => v.id === id);
    if (!p) return;
    const current = Number(cart[id] || 0);
    if (current >= p.stock || current >= 10) { toast('Maximum available quantity reached'); return; }
    cart[id] = current + 1; saveCart(); toast(p.name + ' added to your bag');
  }
  function renderCart() {
    const list = allCartItems();
    const totalItems = countCart();
    $('#cartCount').textContent = String(totalItems);
    $('#drawerCount').textContent = `(${totalItems})`;
    const subtotal = list.reduce((total, {product,qty}) => total + product.price_paise * qty, 0);
    $('#cartSubtotal').textContent = money(subtotal);
    $('#checkoutTrigger').disabled = list.length === 0;
    $('#cartItems').innerHTML = list.length ? list.map(({product:p,qty}) =>
      `<div class="cart-item"><div class="cart-item-image"><img src="${escape(artFor(p))}" alt=""></div><div class="cart-item-info"><small>${escape(p.category)}</small><h4>${escape(p.name)}</h4><strong>${money(p.price_paise * qty)}</strong><div class="qty-controls"><button data-qty="${p.id}" data-delta="-1" aria-label="Decrease ${escape(p.name)}">−</button><span>${qty}</span><button data-qty="${p.id}" data-delta="1" aria-label="Increase ${escape(p.name)}">+</button></div></div><button class="remove-btn" data-remove="${p.id}" aria-label="Remove ${escape(p.name)}">×</button></div>`
    ).join('') : '<div class="cart-empty"><b>YOUR BAG IS EMPTY.</b><p>Good gear is waiting. Start with the collection.</p></div>';
    renderCheckoutSummary();
  }
  function renderCheckoutSummary() {
    const list = allCartItems();
    const subtotal = list.reduce((total,{product,qty}) => total + product.price_paise * qty, 0);
    $('#checkoutLines').innerHTML = list.map(({product,qty}) => `<div class="checkout-line"><span>${escape(product.name)} × ${qty}</span><b>${money(product.price_paise * qty)}</b></div>`).join('');
    $('#summarySubtotal').textContent = money(subtotal);
    $('#summaryShipping').textContent = shipping(subtotal) ? money(shipping(subtotal)) : 'FREE';
    $('#summaryTotal').textContent = money(subtotal + shipping(subtotal));
    $('#payButton').innerHTML = (config.demo_mode ? 'SUBMIT DEMO ORDER' : 'PAY ' + money(subtotal + shipping(subtotal))) + ' <span>↗</span>';
  }
  function closePanels() {
    drawerIsOpen = false; activeDialog = null;
    $('#overlay').hidden = true; $('#cartDrawer').classList.remove('open');
    $('#cartDrawer').setAttribute('aria-hidden', 'true');
    $$('.modal').forEach(m => {m.classList.remove('open');m.setAttribute('aria-hidden', 'true');});
    document.body.classList.remove('modal-open');
  }
  function showPanel(id) {
    closePanels(); $('#overlay').hidden = false; document.body.classList.add('modal-open');
    const el = $('#' + id); el.classList.add('open'); el.setAttribute('aria-hidden', 'false');
    if (id === 'cartDrawer') drawerIsOpen = true;
    else activeDialog = id;
    const input = el.querySelector('input,button'); if (input) input.focus();
  }
  function showResult(title, message, reference, icon) {
    $('#resultTitle').textContent = title; $('#resultText').textContent = message;
    $('#resultRef').textContent = reference || ''; $('#resultRef').hidden = !reference;
    $('#resultIcon').textContent = icon || '✓'; showPanel('resultModal');
  }
  function loadRazorpay() {
    if (window.Razorpay) return Promise.resolve();
    return new Promise((resolve,reject) => {
      const s = document.createElement('script'); s.src = 'https://checkout.razorpay.com/v1/checkout.js';
      s.onload = resolve; s.onerror = () => reject(Error('Payment window could not load'));
      document.head.appendChild(s);
    });
  }
  async function startPayment(response, customer) {
    await loadRazorpay();
    closePanels();
    const options = {
      key:response.key_id, amount:response.amount, currency:'INR', name:'Ace Cricketer',
      description:`Order ${response.order_reference}`, order_id:response.razorpay_order_id,
      prefill:{name:customer.name,email:customer.email,contact:customer.phone},
      theme:{color:'#19272d'},
      handler: async (payment) => {
        try {
          const verified = await api('/api/payments/verify', {method:'POST',body:JSON.stringify({
            order_reference:response.order_reference,
            razorpay_order_id:payment.razorpay_order_id,
            razorpay_payment_id:payment.razorpay_payment_id,
            razorpay_signature:payment.razorpay_signature,
          })});
          if (verified.payment_status === 'captured') {
            cart = {}; saveCart();
            showResult('PAYMENT CONFIRMED.', 'Your payment is verified and your order is ready for the store to process.', response.order_reference, '✓');
          } else {
            showResult('PAYMENT PROCESSING.', 'Your payment was received by checkout, but capture is still pending. Do not pay again; track your order or contact the store.', response.order_reference, '…');
          }
        } catch (err) {
          showResult('VERIFY YOUR PAYMENT.', 'We could not confirm payment yet. Please do not pay twice. Contact the store with the order reference. ' + err.message, response.order_reference, '!');
        }
      },
      modal:{ondismiss:()=>toast('Payment window closed; your reservation expires if unpaid.')}
    };
    new window.Razorpay(options).open();
  }
  async function submitCheckout(event) {
    event.preventDefault();
    const error = $('#checkoutError'); error.hidden = true;
    if (!$('#checkoutForm').reportValidity()) return;
    const items = allCartItems().map(({product,qty}) => ({product_id:product.id,quantity:qty}));
    if (!items.length) {toast('Your bag is empty');return;}
    const f = new FormData(event.currentTarget);
    const customer = Object.fromEntries([...f.entries()].map(([key,value]) => [key, String(value).trim()]));
    const btn = $('#payButton'); btn.disabled = true; btn.textContent = 'CREATING YOUR ORDER…';
    try {
      const result = await api('/api/checkout', {method:'POST',body:JSON.stringify({items,customer})});
      if (result.mode === 'demo') {
        cart = {}; saveCart(); event.currentTarget.reset();
        showResult('PREVIEW ORDER SAVED.', 'A demo order has been recorded in the admin dashboard. No money was charged and this is not an actual purchase.', result.order_reference, '✓');
      } else {
        await startPayment(result, customer);
      }
    } catch (err) {
      error.textContent = err.message; error.hidden = false;
    } finally {btn.disabled = false; renderCheckoutSummary();}
  }
  async function track(event) {
    event.preventDefault(); const f = new FormData(event.currentTarget);
    const ref = String(f.get('reference')).trim(); const email = String(f.get('email')).trim();
    $('#trackResult').textContent = 'Looking for your order…';
    try {
      const data = await api('/api/orders/track', {method:'POST',body:JSON.stringify({reference:ref,email})});
      $('#trackResult').innerHTML = `<div class="track-result-card"><strong>${escape(data.reference)}</strong><div>Payment: ${escape(data.payment_status.toUpperCase())}</div><div>Fulfilment: ${escape(data.fulfillment_status.toUpperCase())}</div><div>Order total: ${money(data.total_paise)}</div><div>${data.items.map(v => `${escape(v.product_name)} × ${v.quantity}`).join(', ')}</div></div>`;
    } catch (err) { $('#trackResult').innerHTML = `<p class="track-error">${escape(err.message)}</p>`; }
  }
  $('#cartTrigger').addEventListener('click', () => showPanel('cartDrawer'));
  $('#checkoutTrigger').addEventListener('click', () => {if(countCart())showPanel('checkoutModal');});
  $('#trackTrigger').addEventListener('click', () => showPanel('trackModal'));
  $('#overlay').addEventListener('click', closePanels);
  $$('[data-close]').forEach(b => b.addEventListener('click', closePanels));
  document.addEventListener('keydown', e => {if(e.key === 'Escape') closePanels();});
  $('#checkoutForm').addEventListener('submit', submitCheckout);
  $('#trackForm').addEventListener('submit', track);
  $('#productGrid').addEventListener('click', e => {
    const b = e.target.closest('[data-add]'); if(b) addItem(Number(b.dataset.add));
  });
  $('#cartItems').addEventListener('click', e => {
    const rm = e.target.closest('[data-remove]');
    if(rm) {delete cart[rm.dataset.remove];saveCart();return;}
    const b = e.target.closest('[data-qty]');
    if (!b) return;
    const id = Number(b.dataset.qty), p = products.find(x => x.id === id), val = Number(cart[id] || 0) + Number(b.dataset.delta);
    if (val <= 0) delete cart[id];
    else if(p && val <= Math.min(10,p.stock)) cart[id] = val;
    else {toast('Maximum available quantity reached');return;}
    saveCart();
  });
  $$('#categoryFilters [data-category]').forEach(b => b.addEventListener('click', () => {
    filter = b.dataset.category;
    $$('#categoryFilters [data-category]').forEach(v=>{v.classList.toggle('active',v===b);v.setAttribute('aria-pressed',String(v===b));});
    renderProducts();
  }));
  $$('[data-jump-category]').forEach(b => b.addEventListener('click', () => {
    $(`#categoryFilters [data-category="${b.dataset.jumpCategory}"]`).click();
    $('#shop').scrollIntoView({behavior:'smooth'});
  }));
  $('#sortSelect').addEventListener('change', renderProducts);
  $('#searchTrigger').addEventListener('click', () => {
    const term = prompt('What cricket gear are you looking for?');
    if (term === null) return;
    search = term.trim().toLowerCase(); renderProducts(); $('#shop').scrollIntoView({behavior:'smooth'});
  });
  $('#mobileMenuTrigger').addEventListener('click', () => {
    $('#mobileNav').hidden = !$('#mobileNav').hidden;
  });
  $$('#mobileNav a').forEach(a => a.addEventListener('click', () => $('#mobileNav').hidden = true));
  $('#year').textContent = String(new Date().getFullYear());
  async function init() {
    try {
      [config, {products}] = await Promise.all([api('/api/config'),api('/api/products')]);
      if (config.demo_mode) $('#demoNotice').hidden = false;
      else $('#footerDisclaimer').textContent = 'Store policies and product information supplied by the merchant.';
      // Drop unavailable cached items and cap quantities to current stock.
      for (const [id, count] of Object.entries(cart)) {
        const p = products.find(x => x.id === Number(id));
        if (!p || !p.stock) delete cart[id];
        else cart[id] = Math.min(Math.max(0,Number(count) || 0),p.stock,10);
      }
      saveCart();renderProducts();
    } catch(err) {
      $('#productGrid').innerHTML = `<div class="empty-products">Cannot load products right now. ${escape(err.message)}</div>`;
      toast('Could not load the catalog');
    }
  }
  init();
})();
