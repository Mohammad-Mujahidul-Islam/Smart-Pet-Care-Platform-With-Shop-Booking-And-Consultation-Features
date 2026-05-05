// Variable to remember if a promo code is active
let currentDiscountPercent = 0; 

document.addEventListener('DOMContentLoaded', () => {
    
    // ==========================================
    // 1. LOAD DEFAULT PETS (Homepage Only)
    // ==========================================
    async function fetchPets() {
        const container = document.getElementById('pets-container');
        if (!container) return; // Only run on pages that have this container

        try {
            const pathParts = window.location.pathname.split('/');
            const userId = pathParts[1] === 'user' ? pathParts[2] : null;
            const endpoint = userId
                ? `/api/featured-pets?user_id=${encodeURIComponent(userId)}`
                : '/api/featured-pets';
            const response = await fetch(endpoint);
            const pets = await response.json();
            container.innerHTML = '';
            
            if (pets.length === 0) {
                container.innerHTML = '<p class="text-gray-500 col-span-full">No relevant featured products found.</p>';
                return;
            }

            pets.forEach(pet => {
                const productLink = userId ? `/user/${userId}/product/${pet.ProductID}` : '/login';
                const seller = pet.SellerName || 'In-house';
                const stockLabel = pet.StockQuantity > 0 ? `${pet.StockQuantity} in stock` : 'Out of stock';
                
                const petCard = `
                <a href="${productLink}" class="bg-white rounded-2xl shadow-sm border overflow-hidden flex flex-col cursor-pointer hover:shadow-xl hover:-translate-y-1 transition-all duration-300 block">
                    <div class="p-3 md:p-4">
                        <p class="text-xs text-gray-500">${pet.PetCategory || 'General'} • Seller: ${seller}</p>
                        <h3 class="text-sm md:text-base font-bold text-[#2C3E50] truncate">${pet.Name}</h3>
                        <p class="text-xs text-gray-500 mt-1">Qty: ${stockLabel}</p>
                        <p class="text-sm md:text-base font-bold text-[#5AB9B4] mt-2">$${pet.Price}</p>
                    </div>
                </a>`;
                container.innerHTML += petCard;
            });
        } catch (error) {
            container.innerHTML = '<p class="text-red-500 col-span-full">Failed to load pets.</p>';
        }
    }
    fetchPets();

    // ==========================================
    // 1b. SHOP FOR PET — drag horizontally (hold & pull left/right)
    // ==========================================
    (function setupShopPetDragScroll() {
        const strip = document.getElementById('shop-pet-categories-scroll');
        if (!strip) return;

        strip.querySelectorAll('img').forEach((img) => {
            img.draggable = false;
        });

        strip.querySelectorAll('a[href]').forEach((anchor) => {
            anchor.draggable = false;
            anchor.addEventListener('dragstart', (ev) => {
                ev.preventDefault();
            });
        });

        strip.addEventListener(
            'dragstart',
            (ev) => {
                ev.preventDefault();
            },
            true
        );

        const DRAG_THRESHOLD = 5;
        let activePointerId = null;
        let startClientX = 0;
        let startScrollLeft = 0;
        let dragActive = false;
        let suppressNextClick = false;

        strip.addEventListener('pointerdown', (e) => {
            if (e.pointerType === 'mouse' && e.button !== 0) return;
            activePointerId = e.pointerId;
            startClientX = e.clientX;
            startScrollLeft = strip.scrollLeft;
            dragActive = false;
            suppressNextClick = false;
            strip.classList.add('shop-pet-pulling');
            try {
                strip.setPointerCapture(e.pointerId);
            } catch (_) {
                /* noop */
            }
        });

        strip.addEventListener(
            'pointermove',
            (e) => {
                if (e.pointerId !== activePointerId) return;
                const dx = e.clientX - startClientX;
                if (!dragActive && Math.abs(dx) >= DRAG_THRESHOLD) {
                    dragActive = true;
                }
                if (dragActive) {
                    e.preventDefault();
                    strip.scrollLeft = startScrollLeft - dx;
                }
            },
            { passive: false }
        );

        function finishPointerDrag(e) {
            if (e.pointerId !== activePointerId) return;
            try {
                if (typeof strip.hasPointerCapture === 'function' && strip.hasPointerCapture(e.pointerId)) {
                    strip.releasePointerCapture(e.pointerId);
                }
            } catch (_) {
                /* noop */
            }
            strip.classList.remove('shop-pet-pulling');
            if (dragActive) {
                suppressNextClick = true;
            }
            activePointerId = null;
            dragActive = false;
        }

        strip.addEventListener('pointerup', finishPointerDrag);
        strip.addEventListener('pointercancel', finishPointerDrag);

        strip.addEventListener(
            'click',
            (e) => {
                if (suppressNextClick) {
                    e.preventDefault();
                    e.stopPropagation();
                    suppressNextClick = false;
                }
            },
            true
        );
    })();

    // ==========================================
    // 2. PROFILE DROPDOWN
    // ==========================================
    const profileBtn = document.getElementById('profile-btn');
    const dropdown = document.getElementById('profile-dropdown');
    
    if (profileBtn && dropdown) {
        profileBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('hidden');
        });
        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && !profileBtn.contains(e.target)) dropdown.classList.add('hidden');
        });
    }

    // ==========================================
    // 3. AUTOCOMPLETE & LIVE SEARCH
    // ==========================================
    const searchInput = document.getElementById('search-input');
    const searchDropdown = document.getElementById('search-dropdown');

    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const query = e.target.value.trim();
                if (query.length > 0) {
                    const pathParts = window.location.pathname.split('/');
                    const userId = pathParts[1] === 'user' ? pathParts[2] : null;
                    const basePath = userId ? `/user/${userId}/browse` : '/browse';
                    window.location.href = `${basePath}?q=${encodeURIComponent(query)}`;
                }
            }
        });

        if(searchDropdown) {
            searchInput.addEventListener('input', async (e) => {
                const query = e.target.value.trim();
                const pathParts = window.location.pathname.split('/');
                const userId = pathParts[1] === 'user' ? pathParts[2] : null;

                if (query.length === 0) {
                    searchDropdown.classList.add('hidden');
                    return;
                }

                try {
                    const response = await fetch(`/api/search?q=${query}`);
                    const allPets = await response.json();
                    const pets = allPets.slice(0, 5);

                    if (pets.length === 0) {
                        searchDropdown.innerHTML = `<div class="p-4 text-sm text-gray-500 font-medium">No results found for "${query}"</div>`;
                        searchDropdown.classList.remove('hidden');
                        return;
                    }

                    const categories = [...new Set(pets.map(p => p.PetCategory))];
                    let dropdownHTML = `<div class="px-5 py-3"><span class="text-xs font-bold text-gray-500">Search suggestions for <span class="text-[#5AB9B4]">${query}</span></span></div>`;

                    categories.forEach(cat => {
                        const basePath = userId ? `/user/${userId}/browse` : '/browse';
                        dropdownHTML += `
                            <a href="${basePath}?category=${encodeURIComponent(cat)}" class="px-5 py-1.5 hover:bg-gray-50 cursor-pointer flex justify-between items-center group transition-colors block">
                                <span class="text-sm text-gray-600 group-hover:text-[#5AB9B4] capitalize">
                                    <span class="text-[#5AB9B4] font-medium">${query}</span> in ${cat}
                                </span>
                            </a>`;
                    });

                    dropdownHTML += `<div class="px-5 py-2 mt-2"><span class="text-xs font-bold text-[#2C3E50]">Products</span></div>`;

                    pets.forEach(pet => {
                        const productLink = userId ? `/user/${userId}/product/${pet.ProductID}` : '/login';
                        dropdownHTML += `
                            <a href="${productLink}" class="px-5 py-2 hover:bg-gray-50 transition-colors block">
                                <div class="flex-1">
                                    <h4 class="text-sm font-medium text-gray-700">${pet.Name}</h4>
                                    <p class="text-xs text-gray-500">${pet.PetCategory || 'General'}</p>
                                </div>
                            </a>`;
                    });

                    searchDropdown.innerHTML = dropdownHTML;
                    searchDropdown.classList.remove('hidden');

                } catch (error) {
                    console.error("Search failed:", error);
                }
            });

            document.addEventListener('click', (e) => {
                if (!searchInput.contains(e.target) && !searchDropdown.contains(e.target)) {
                    searchDropdown.classList.add('hidden');
                }
            });
        }
    }

    // ==========================================
    // 4. NOTIFICATION BELL LOGIC
    // ==========================================
    const notifBtn = document.getElementById('notification-btn');
    const notifDropdown = document.getElementById('notification-dropdown');
    const notifList = document.getElementById('notification-list');
    const notifBadge = document.getElementById('notif-badge');

    if (notifBtn && notifDropdown) {
        notifBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            notifDropdown.classList.toggle('hidden');
            if (!notifDropdown.classList.contains('hidden')) {
                if (notifBadge) notifBadge.classList.add('hidden'); // Hide red dot when opened
            }
        });
        
        document.addEventListener('click', (e) => {
            if (!notifDropdown.contains(e.target) && !notifBtn.contains(e.target)) {
                notifDropdown.classList.add('hidden');
            }
        });

        async function loadNotifications() {
            const pathParts = window.location.pathname.split('/');
            const userId = pathParts[1] === 'user' ? pathParts[2] : null;
            if (!userId || !notifList) return;

            try {
                const response = await fetch(`/api/notifications/${userId}`);
                const notifications = await response.json();
                
                notifList.innerHTML = '';
                if (notifications.length === 0) {
                    notifList.innerHTML = '<p class="text-sm text-gray-500 p-4 text-center">No new notifications.</p>';
                    return;
                }

                let hasUnread = false;
                notifications.forEach(notif => {
                    if (!notif.IsRead) hasUnread = true;
                    
                    const date = new Date(notif.CreatedAt).toLocaleDateString();
                    notifList.innerHTML += `
                        <div class="p-4 border-b border-gray-50 last:border-0 hover:bg-gray-50 transition-colors ${notif.IsRead ? 'opacity-75' : 'bg-blue-50/30'}">
                            <p class="text-sm text-[#2C3E50]">${notif.Message}</p>
                            <span class="text-xs text-gray-400 mt-1 block">${date}</span>
                        </div>
                    `;
                });

                if (hasUnread && notifBadge) notifBadge.classList.remove('hidden');

            } catch (error) {
                console.error("Failed to load notifications", error);
            }
        }
        
        loadNotifications(); // Run on page load
    }

    // ==========================================
    // 5. CART DRAWER & QUANTITY LOGIC
    // ==========================================
    const cartBtn = document.getElementById('cart-drawer-btn');
    const cartPanel = document.getElementById('cart-panel');
    const cartBackdrop = document.getElementById('cart-backdrop');
    const closeCartBtn = document.getElementById('close-cart-btn');

    function toggleCart() {
        if (!cartPanel || !cartBackdrop) return;
        cartPanel.classList.toggle('translate-x-full');
        cartBackdrop.classList.toggle('hidden');
        if (!cartPanel.classList.contains('translate-x-full')) {
            loadCartItems();
        }
    }

    if (cartBtn) cartBtn.addEventListener('click', toggleCart);
    if (closeCartBtn) closeCartBtn.addEventListener('click', toggleCart);
    if (cartBackdrop) cartBackdrop.addEventListener('click', toggleCart);

    // Global function to add a new item to cart
    window.addToCart = async function(userId, productId, quantity = 1) {
        if (!userId) {
            alert("Please sign in to add items to your cart.");
            return;
        }

        try {
            const response = await fetch('/api/cart/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId, product_id: productId, quantity: quantity })
            });
            const result = await response.json();
            
            if (response.ok) { 
                if (cartPanel && cartBackdrop) {
                    cartPanel.classList.remove('translate-x-full');
                    cartBackdrop.classList.remove('hidden');
                    loadCartItems(); 
                }
            } else { 
                alert(result.error || "Failed to add item to cart"); 
            }
        } catch (error) {
            console.error("Error adding to cart:", error);
            alert("An error occurred connecting to the server.");
        }
    };

    // Global function to update quantities (+ / -) in the cart drawer
    window.updateCartItem = async function(userId, productId, action) {
        try {
            const response = await fetch('/api/cart/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId, product_id: productId, action: action })
            });
            const result = await response.json();
            if (response.ok) { 
                loadCartItems(); 
            } else { 
                alert(result.error || "Failed to update cart"); 
            }
        } catch (error) {
            console.error("Error updating cart:", error);
        }
    };

    // ==========================================
    // 6. PROMO CODE VERIFICATION
    // ==========================================
    const applyPromoBtn = document.getElementById('apply-promo-btn');
    const promoInput = document.getElementById('promo-code-input');
    const promoMessage = document.getElementById('promo-message');

    if (applyPromoBtn && promoInput) {
        applyPromoBtn.addEventListener('click', async () => {
            const code = promoInput.value.trim().toUpperCase();
            const pathParts = window.location.pathname.split('/');
            const userId = pathParts[1] === 'user' ? pathParts[2] : null;

            if (!userId) {
                if (promoMessage) {
                    promoMessage.textContent = "Please log in to use codes.";
                    promoMessage.className = "text-xs font-bold text-red-500";
                    promoMessage.classList.remove('hidden');
                }
                return;
            }

            if (code === '') return;

            applyPromoBtn.disabled = true;
            applyPromoBtn.textContent = "...";

            try {
                const response = await fetch('/api/cart/validate-offer', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: code, user_id: userId })
                });

                const result = await response.json();

                if (response.ok) {
                    currentDiscountPercent = result.discount; 
                    if (promoMessage) {
                        promoMessage.textContent = "✅ " + result.message;
                        promoMessage.className = "text-xs font-bold text-green-600";
                        promoMessage.classList.remove('hidden');
                    }
                    loadCartItems(); 
                } else {
                    currentDiscountPercent = 0;
                    if (promoMessage) {
                        promoMessage.textContent = "❌ " + result.error;
                        promoMessage.className = "text-xs font-bold text-red-500";
                        promoMessage.classList.remove('hidden');
                    }
                    loadCartItems();
                }
            } catch (error) {
                console.error(error);
            } finally {
                applyPromoBtn.disabled = false;
                applyPromoBtn.textContent = "Apply";
            }
        });
    }

    // ==========================================
    // 7. RENDER CART ITEMS & MATH
    // ==========================================
    async function loadCartItems() {
        const container = document.getElementById('cart-items-container');
        const totalDisplay = document.getElementById('cart-total');
        const subtotalDisplay = document.getElementById('cart-subtotal');
        const discountRow = document.getElementById('discount-row');
        const discountPercentDisplay = document.getElementById('discount-percent-display');
        const discountAmountDisplay = document.getElementById('cart-discount-amount');

        if (!container || !totalDisplay) return;
        
        const pathParts = window.location.pathname.split('/');
        const userId = pathParts[1] === 'user' ? pathParts[2] : null;

        if (!userId) {
            container.innerHTML = '<p class="text-gray-500 text-center mt-10">Please sign in to view your cart.</p>';
            return;
        }

        try {
            const response = await fetch(`/api/cart/${userId}`);
            const items = await response.json();
            container.innerHTML = '';
            let total = 0;

            if (items.length === 0) {
                container.innerHTML = '<p class="text-gray-500 text-center mt-10">Your cart is empty.</p>';
                if (subtotalDisplay) subtotalDisplay.textContent = '$0.00';
                totalDisplay.textContent = '$0.00';
                if (discountRow) discountRow.classList.add('hidden');
                currentDiscountPercent = 0; 
                return;
            }

            items.forEach(item => {
                total += (item.Price * item.Quantity);
                container.innerHTML += `
                    <div class="flex items-center gap-4 border-b pb-4 mt-4">
                        <img src="https://images.unsplash.com/photo-1543466835-00a7907e9de1?w=100&fit=crop" class="w-16 h-16 rounded-lg object-cover">
                        <div class="flex-1">
                            <h4 class="font-bold text-[#2C3E50] leading-tight">${item.Name}</h4>
                            
                            <div class="flex items-center mt-2">
                                <div class="flex items-center border border-gray-300 rounded-lg bg-white shadow-sm w-fit">
                                    <button onclick="updateCartItem(${userId}, ${item.ProductID}, 'decrease')" class="px-3 py-1 text-gray-600 hover:bg-gray-100 hover:text-red-500 rounded-l-lg transition-colors cursor-pointer font-bold">-</button>
                                    <span class="px-4 py-1 text-sm font-semibold text-[#2C3E50] border-x border-gray-300">${item.Quantity}</span>
                                    <button onclick="updateCartItem(${userId}, ${item.ProductID}, 'increase')" class="px-3 py-1 text-gray-600 hover:bg-gray-100 hover:text-[#5AB9B4] rounded-r-lg transition-colors cursor-pointer font-bold">+</button>
                                </div>
                            </div>
                            
                        </div>
                        <p class="font-bold text-[#5AB9B4]">$${(item.Price * item.Quantity).toFixed(2)}</p>
                    </div>
                `;
            });
            
            if (subtotalDisplay) subtotalDisplay.textContent = '$' + total.toFixed(2);

            if (currentDiscountPercent > 0 && discountRow && discountPercentDisplay && discountAmountDisplay) {
                const discountAmount = total * (currentDiscountPercent / 100);
                const finalTotal = total - discountAmount;
                
                discountPercentDisplay.textContent = currentDiscountPercent;
                discountAmountDisplay.textContent = '-$' + discountAmount.toFixed(2);
                discountRow.classList.remove('hidden');
                
                totalDisplay.textContent = '$' + finalTotal.toFixed(2);
            } else {
                if (discountRow) discountRow.classList.add('hidden');
                totalDisplay.textContent = '$' + total.toFixed(2);
            }

        } catch (error) {
            container.innerHTML = '<p class="text-red-500 text-center mt-10">Failed to load cart.</p>';
        }
    }
});