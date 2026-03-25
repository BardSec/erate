'use strict';

document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss alerts after 5 seconds
    document.querySelectorAll('.alert-dismissible').forEach(function(alert) {
        setTimeout(function() {
            var bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });

    // Sortable tables
    document.querySelectorAll('th[data-sort]').forEach(function(header) {
        header.addEventListener('click', function() {
            var table = this.closest('table');
            var tbody = table.querySelector('tbody');
            var rows = Array.from(tbody.querySelectorAll('tr'));
            var colIndex = Array.from(this.parentNode.children).indexOf(this);
            var ascending = this.dataset.sortDir !== 'asc';
            this.dataset.sortDir = ascending ? 'asc' : 'desc';

            rows.sort(function(a, b) {
                var aVal = a.children[colIndex] ? a.children[colIndex].textContent.trim() : '';
                var bVal = b.children[colIndex] ? b.children[colIndex].textContent.trim() : '';
                // Try numeric sort
                var aNum = parseFloat(aVal.replace(/[$,%]/g, ''));
                var bNum = parseFloat(bVal.replace(/[$,%]/g, ''));
                if (!isNaN(aNum) && !isNaN(bNum)) {
                    return ascending ? aNum - bNum : bNum - aNum;
                }
                return ascending ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
            });

            rows.forEach(function(row) { tbody.appendChild(row); });
        });
    });

    // Table search/filter
    document.querySelectorAll('[data-table-search]').forEach(function(input) {
        var tableId = input.dataset.tableSearch;
        var table = document.getElementById(tableId);
        if (!table) return;
        input.addEventListener('input', function() {
            var query = this.value.toLowerCase();
            var rows = table.querySelectorAll('tbody tr');
            rows.forEach(function(row) {
                var text = row.textContent.toLowerCase();
                row.style.display = text.includes(query) ? '' : 'none';
            });
        });
    });
});
