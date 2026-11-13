document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("select.customer-select").forEach((select) => {
        const search = select.parentElement.querySelector(
            ".customer-choice-search"
        );
        if (!search) return;

        const options = Array.from(select.options).map((option) => ({
            option,
            searchText: `${option.value} ${option.textContent}`.toLowerCase(),
        }));

        search.addEventListener("input", () => {
            const query = search.value.trim().toLowerCase();
            options.forEach(({ option, searchText }) => {
                option.hidden = Boolean(
                    query && option.value && !searchText.includes(query)
                );
            });

            const selectedOption = options.find(
                ({ option }) => option.value === select.value
            );
            if (selectedOption?.option.hidden) {
                select.value = "";
            }
        });
    });
});
