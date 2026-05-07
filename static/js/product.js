document.addEventListener('DOMContentLoaded', () => {
    const addToCartBtn = document.getElementById('add-to-cart-btn');
    const statusText = document.getElementById('cart-status');
    
    // Quantity Controls
    const qtyMinus = document.getElementById('qty-minus');
    const qtyPlus = document.getElementById('qty-plus');
    const qtyDisplay = document.getElementById('qty-display');
    const maxStock = parseInt(document.getElementById('max-stock').value);
    
    let currentQty = 1;

    // If out of stock, disable the quantity selector and cart button
    if (maxStock === 0) {
        currentQty = 0;
        if (qtyDisplay) qtyDisplay.textContent = 0;
        if (addToCartBtn) {
            addToCartBtn.disabled = true;
            addToCartBtn.innerHTML = "Out of Stock";
            addToCartBtn.classList.replace("text-teal-500", "text-gray-400");
            addToCartBtn.classList.replace("border-teal-500", "border-gray-300");
        }
    }

    // Logic for the + / - buttons on the product page
    if (qtyMinus && qtyPlus && qtyDisplay && maxStock > 0) {
        qtyMinus.addEventListener('click', () => {
            if (currentQty > 1) {
                currentQty--;
                qtyDisplay.textContent = currentQty;
            }
        });

        qtyPlus.addEventListener('click', () => {
            if (currentQty < maxStock) {
                currentQty++;
                qtyDisplay.textContent = currentQty;
            }
        });
    }

    // Add to Cart Logic
    if (addToCartBtn && maxStock > 0) {
        addToCartBtn.addEventListener('click', async () => {
            const userId = document.getElementById('current-user-id').value;
            const productId = document.getElementById('current-product-id').value;
            const originalText = addToCartBtn.innerHTML;
            
            addToCartBtn.innerHTML = "Adding...";
            addToCartBtn.disabled = true;

            try {
                const response = await fetch('/api/cart/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    // WE NOW SEND THE SELECTED QUANTITY!
                    body: JSON.stringify({ user_id: userId, product_id: productId, quantity: currentQty })
                });

                const result = await response.json();
                statusText.classList.remove('hidden');
                
                if (response.ok) {
                    statusText.textContent = "✅ " + result.message;
                    statusText.className = "mt-4 text-sm font-bold text-green-600";
                    addToCartBtn.innerHTML = "Added!";
                    
                    // Reset the selector back to 1
                    currentQty = 1;
                    qtyDisplay.textContent = currentQty;
                } else {
                    statusText.textContent = "❌ " + (result.error || "Failed to add.");
                    statusText.className = "mt-4 text-sm font-bold text-red-600";
                    addToCartBtn.innerHTML = originalText;
                    addToCartBtn.disabled = false;
                }
            } catch (error) {
                statusText.classList.remove('hidden');
                statusText.textContent = "❌ Server Error.";
                statusText.className = "mt-4 text-sm font-bold text-red-600";
                addToCartBtn.innerHTML = originalText;
                addToCartBtn.disabled = false;
            }
        });
    }
});