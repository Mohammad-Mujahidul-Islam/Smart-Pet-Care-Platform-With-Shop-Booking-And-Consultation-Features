document.addEventListener('DOMContentLoaded', async () => {
    
    // --- FILTER COLLAPSE/EXPAND LOGIC ---
    const filterHeaders = document.querySelectorAll('.filter-header');
    filterHeaders.forEach(header => {
        header.addEventListener('click', () => {
            const content = header.nextElementSibling;
            const icon = header.querySelector('span');
            
            // Toggle visibility
            content.classList.toggle('hidden');
            
            // Flip the arrow icon
            if (content.classList.contains('hidden')) {
                icon.style.transform = 'rotate(180deg)';
            } else {
                icon.style.transform = 'rotate(0deg)';
            }
        });
    });

    // --- BROWSE GRID & SLIDER LOGIC ---
    const container = document.getElementById('browse-container');
    const title = document.getElementById('browse-title');
    
    // Grab the inputs and the new range sliders
    const minPriceInput = document.getElementById('min-price');
    const maxPriceInput = document.getElementById('max-price');
    const minRange = document.getElementById('min-range');
    const maxRange = document.getElementById('max-range');
    const sliderTrack = document.getElementById('slider-track');

    if (!container) return; 

    // Read the URL to see what the user is searching/filtering for
    const urlParams = new URLSearchParams(window.location.search);
    const query = urlParams.get('q');
    const category = urlParams.get('category'); // legacy single category
    const categoriesRaw = urlParams.get('categories'); // comma-separated

    const selectedCategories = (categoriesRaw ? categoriesRaw.split(',') : (category ? [category] : []))
        .map(c => decodeURIComponent(c).trim())
        .filter(Boolean);
    
    let endpoint = '/api/browse-products?';
    if (query) endpoint += `q=${encodeURIComponent(query)}&`;
    if (selectedCategories.length > 0) endpoint += `categories=${encodeURIComponent(selectedCategories.join(','))}`;

    // Set the page title
    if (title) {
        if (query) title.innerHTML = `Results for <span class="italic text-[#5AB9B4]">"${query}"</span>`;
        else if (selectedCategories.length === 1) title.innerHTML = `${selectedCategories[0]} Category`;
        else if (selectedCategories.length > 1) title.innerHTML = `Categories: ${selectedCategories.join(', ')}`;
        else title.innerHTML = "All Products";
    }

    // --- MULTI CATEGORY FILTER UI ---
    const categoryCheckboxes = Array.from(document.querySelectorAll('.category-checkbox'));
    const applyCategoryBtn = document.getElementById('apply-category-btn');
    const clearCategoryBtn = document.getElementById('clear-category-btn');

    function syncCategoryCheckboxesFromUrl() {
        if (categoryCheckboxes.length === 0) return;
        const set = new Set(selectedCategories);
        categoryCheckboxes.forEach(cb => {
            cb.checked = set.has(cb.value);
        });
    }

    function updateUrlWithCategories(categories) {
        const url = new URL(window.location.href);
        url.searchParams.delete('category'); // remove legacy single category
        if (categories.length > 0) url.searchParams.set('categories', categories.join(','));
        else url.searchParams.delete('categories');
        window.location.href = url.toString();
    }

    syncCategoryCheckboxesFromUrl();
    if (applyCategoryBtn) {
        applyCategoryBtn.addEventListener('click', () => {
            const cats = categoryCheckboxes.filter(cb => cb.checked).map(cb => cb.value);
            updateUrlWithCategories(cats);
        });
    }
    if (clearCategoryBtn) {
        clearCategoryBtn.addEventListener('click', () => {
            updateUrlWithCategories([]);
        });
    }

    let allPets = []; 

    // Function to draw the products on the screen
    function renderPets(petsToRender) {
        container.innerHTML = '';
        if (petsToRender.length === 0) {
            container.innerHTML = '<p class="text-gray-500 col-span-full">No products found matching your criteria.</p>';
            return;
        }

        const pathParts = window.location.pathname.split('/');
        const userId = pathParts[1] === 'user' ? pathParts[2] : null;

        petsToRender.forEach(pet => {
            const productLink = userId ? `/user/${userId}/product/${pet.ProductID}` : '/login';
            const seller = pet.SellerName || 'In-house';
            
            const stockLabel = pet.StockQuantity > 0 ? `${pet.StockQuantity} in stock` : 'Out of stock';

            const petCard = `
            <a href="${productLink}" class="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden flex flex-col cursor-pointer hover:shadow-xl hover:-translate-y-1 transition-all duration-300 block">
                <div class="p-4 md:p-5">
                    <span class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1 block">${pet.PetCategory || 'General'}</span>
                    <h3 class="text-base md:text-lg font-bold text-[#2C3E50] truncate">${pet.Name}</h3>
                    <p class="text-xs text-gray-500 mt-1">Seller: ${seller}</p>
                    <p class="text-xs text-gray-500 mt-1">Qty: ${stockLabel}</p>
                    <p class="text-lg md:text-xl font-bold text-[#5AB9B4] mt-2">$${pet.Price}</p>
                </div>
            </a>`;
            container.innerHTML += petCard;
        });
    }

    try {
        const response = await fetch(endpoint);
        allPets = await response.json();
        
        // Dynamic Pricing Slider Setup
        if (allPets.length > 0 && minPriceInput && maxPriceInput && minRange && maxRange) {
            
            const prices = allPets.map(p => parseFloat(p.Price));
            const absoluteMin = Math.floor(Math.min(...prices));
            const absoluteMax = Math.ceil(Math.max(...prices));

            minPriceInput.value = absoluteMin;
            maxPriceInput.value = absoluteMax;
            
            minRange.min = absoluteMin; minRange.max = absoluteMax; minRange.value = absoluteMin;
            maxRange.min = absoluteMin; maxRange.max = absoluteMax; maxRange.value = absoluteMax;

            function updateTrack() {
                let minVal = parseFloat(minRange.value);
                let maxVal = parseFloat(maxRange.value);
                
                if (absoluteMax - absoluteMin === 0) {
                    sliderTrack.style.left = '0%';
                    sliderTrack.style.width = '100%';
                    return;
                }
                
                const percent1 = ((minVal - absoluteMin) / (absoluteMax - absoluteMin)) * 100;
                const percent2 = ((maxVal - absoluteMin) / (absoluteMax - absoluteMin)) * 100;
                sliderTrack.style.left = percent1 + '%';
                sliderTrack.style.width = (percent2 - percent1) + '%';
            }

            function filterPets() {
                const currentMin = parseFloat(minPriceInput.value) || 0;
                const currentMax = parseFloat(maxPriceInput.value) || Infinity;
                const filtered = allPets.filter(p => parseFloat(p.Price) >= currentMin && parseFloat(p.Price) <= currentMax);
                renderPets(filtered);
            }

            minRange.addEventListener('input', () => {
                if (parseFloat(minRange.value) > parseFloat(maxRange.value)) minRange.value = maxRange.value;
                minPriceInput.value = minRange.value;
                updateTrack();
                filterPets();
            });

            maxRange.addEventListener('input', () => {
                if (parseFloat(maxRange.value) < parseFloat(minRange.value)) maxRange.value = minRange.value;
                maxPriceInput.value = maxRange.value;
                updateTrack();
                filterPets();
            });

            minPriceInput.addEventListener('input', () => {
                minRange.value = minPriceInput.value;
                updateTrack();
                filterPets();
            });

            maxPriceInput.addEventListener('input', () => {
                maxRange.value = maxPriceInput.value;
                updateTrack();
                filterPets();
            });

            updateTrack(); 
        }

        // Render the products initially
        renderPets(allPets);

    } catch (error) {
        console.error(error);
        container.innerHTML = '<p class="text-red-500 col-span-full">Failed to load products. Please check your connection.</p>';
    }
});