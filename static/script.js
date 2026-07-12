document.addEventListener("DOMContentLoaded", () => {
    const textarea = document.getElementById("news_text");
    const charCount = document.getElementById("charCount");
    const readTimeEstimate = document.getElementById("readTimeEstimate");
    const analyzeForm = document.getElementById("analyzeForm");
    const analyzeButton = document.getElementById("analyzeButton");
    const loadingSpinner = document.getElementById("loadingSpinner");
    const analysisLoadingStage = document.getElementById("analysisLoadingStage");
    const themeToggle = document.getElementById("themeToggle");
    const themeToggleLabel = themeToggle?.querySelector(".theme-toggle-label");
    const themeToggleIcon = themeToggle?.querySelector(".theme-toggle-icon");
    const copyResultButton = document.getElementById("copyResultButton");
    const clearTextButton = document.getElementById("clearTextButton");
    const todayNewsButton = document.getElementById("todayNewsButton");
    const refreshNewsButton = document.getElementById("refreshNewsButton");
    const todayNewsSection = document.getElementById("todayNewsSection");
    const todayNewsList = document.getElementById("todayNewsList");
    const todayNewsMessage = document.getElementById("todayNewsMessage");
    const todayNewsHeading = document.getElementById("todayNewsHeading");
    const newsLoadingState = document.getElementById("newsLoadingState");
    const scrollProgressBar = document.getElementById("scrollProgressBar");
    const storyScenes = document.querySelectorAll("[data-story-scene]");
    const storySteps = document.querySelectorAll("[data-story-target]");

    const applyThemeLabel = (isDark) => {
        if (!themeToggle) {
            return;
        }

        if (themeToggleLabel) {
            themeToggleLabel.textContent = isDark ? "Light" : "Dark";
        }

        if (themeToggleIcon) {
            themeToggleIcon.textContent = isDark ? "L" : "D";
        }

        themeToggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
    };

    if (textarea && charCount) {
        const updateCount = () => {
            charCount.textContent = `${textarea.value.length} / 3000 characters`;

            if (readTimeEstimate) {
                const words = textarea.value.trim() ? textarea.value.trim().split(/\s+/).length : 0;
                const minutes = words === 0 ? 0 : Math.max(1, Math.ceil(words / 180));
                readTimeEstimate.textContent = `Estimated reading time: ${minutes} min`;
            }
        };

        textarea.addEventListener("input", updateCount);
        updateCount();

        if (clearTextButton) {
            clearTextButton.addEventListener("click", () => {
                textarea.value = "";
                textarea.focus();
                updateCount();
            });
        }
    }

    if (analyzeForm && analyzeButton && loadingSpinner) {
        analyzeForm.addEventListener("submit", () => {
            analyzeButton.disabled = true;
            loadingSpinner.classList.remove("hidden");
            analysisLoadingStage?.classList.remove("hidden");
            const buttonText = analyzeButton.querySelector(".button-text");
            if (buttonText) {
                buttonText.textContent = "Analyzing Now";
            }
        });
    }

    const savedTheme = localStorage.getItem("theme");
    if (savedTheme === "dark") {
        document.body.classList.add("dark-mode");
    }
    applyThemeLabel(document.body.classList.contains("dark-mode"));

    if (themeToggle) {
        themeToggle.addEventListener("click", () => {
            document.body.classList.toggle("dark-mode");
            const isDark = document.body.classList.contains("dark-mode");
            localStorage.setItem("theme", isDark ? "dark" : "light");
            applyThemeLabel(isDark);
        });
    }

    if (copyResultButton) {
        copyResultButton.addEventListener("click", async () => {
            const resultText = document.querySelector(".result-layout")?.innerText || "";
            try {
                await navigator.clipboard.writeText(resultText);
                copyResultButton.textContent = "Copied";
                setTimeout(() => {
                    copyResultButton.textContent = "Copy Result";
                }, 1500);
            } catch (error) {
                copyResultButton.textContent = "Copy Failed";
            }
        });
    }

    const escapeHtml = (value) =>
        String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");

    const renderNewsItems = (items) => {
        if (!todayNewsList) {
            return;
        }

        if (!items.length) {
            todayNewsList.innerHTML = `
                <div class="news-empty-state">
                    <p>No headlines are available right now.</p>
                </div>
            `;
            return;
        }

        todayNewsList.innerHTML = items
            .map(
                (item, index) => `
                    <article class="news-item">
                        <span class="feature-index">${String(index + 1).padStart(2, "0")}</span>
                        <h3>${escapeHtml(item.title)}</h3>
                        <p>${escapeHtml(item.published_at || "Latest update")}</p>
                        <a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer" class="ghost-button">Open Source</a>
                    </article>
                `
            )
            .join("");
    };

    const loadTodaysNews = async () => {
        if (!todayNewsSection || !todayNewsMessage || !todayNewsList) {
            return;
        }

        todayNewsSection.classList.remove("hidden");
        todayNewsMessage.textContent = "Fetching the latest available headlines...";
        todayNewsList.innerHTML = "";
        newsLoadingState?.classList.remove("hidden");

        try {
            const response = await fetch("/todays-news", {
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            const data = await response.json();
            newsLoadingState?.classList.add("hidden");

            if (todayNewsHeading && data.date_label) {
                todayNewsHeading.textContent = `Current headlines for ${data.date_label}`;
            }

            todayNewsMessage.textContent = data.message || "Current headlines loaded.";
            renderNewsItems(Array.isArray(data.items) ? data.items : []);
            todayNewsSection.scrollIntoView({ behavior: "smooth", block: "start" });
        } catch (error) {
            newsLoadingState?.classList.add("hidden");
            todayNewsMessage.textContent = "News could not be loaded right now. Please try again.";
            renderNewsItems([]);
        }
    };

    if (todayNewsButton) {
        todayNewsButton.addEventListener("click", loadTodaysNews);
    }

    if (refreshNewsButton) {
        refreshNewsButton.addEventListener("click", loadTodaysNews);
    }

    const updateScrollProgress = () => {
        if (!scrollProgressBar) {
            return;
        }

        const scrollableHeight = document.documentElement.scrollHeight - window.innerHeight;
        const progress = scrollableHeight > 0 ? window.scrollY / scrollableHeight : 0;
        scrollProgressBar.style.transform = `scaleX(${Math.min(1, Math.max(0, progress))})`;
    };

    if (storyScenes.length && storySteps.length) {
        const sceneObserver = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (!entry.isIntersecting) {
                        return;
                    }

                    const activeId = entry.target.id;
                    storyScenes.forEach((scene) => {
                        scene.classList.toggle("is-active", scene.id === activeId);
                    });

                    storySteps.forEach((step) => {
                        step.classList.toggle("is-active", step.dataset.storyTarget === activeId);
                    });
                });
            },
            {
                rootMargin: "-30% 0px -35% 0px",
                threshold: 0.25,
            }
        );

        storyScenes.forEach((scene) => sceneObserver.observe(scene));

        storySteps.forEach((step) => {
            step.addEventListener("click", () => {
                const target = document.getElementById(step.dataset.storyTarget || "");
                target?.scrollIntoView({ behavior: "smooth", block: "center" });
            });
        });
    }

    window.addEventListener("scroll", updateScrollProgress, { passive: true });
    updateScrollProgress();

    const staggerItems = document.querySelectorAll(".stagger-item");
    staggerItems.forEach((item, index) => {
        item.style.animationDelay = `${0.08 * (index + 1)}s`;
    });
});
