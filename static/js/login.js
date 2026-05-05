document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('login-form');
    const messageBox = document.getElementById('message-box');

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;

        try {
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            const result = await response.json();
            messageBox.classList.remove('hidden');

            if (response.ok) {
                messageBox.textContent = result.message;
                messageBox.className = "text-sm text-center text-green-600 mt-2 font-bold";
                setTimeout(() => {
                    if (result.pending) {
                        window.location.href = "/pending-approval";
                        return;
                    }
                    window.location.href = "/user/" + result.user.UserID;
                }, 1000);
            } else {
                messageBox.textContent = result.error || "Login failed.";
                messageBox.className = "text-sm text-center text-red-600 mt-2 font-bold";
            }
        } catch (error) {
            messageBox.textContent = "Server error. Please try again later.";
            messageBox.className = "text-sm text-center text-red-600 mt-2 font-bold";
            messageBox.classList.remove('hidden');
        }
    });
});