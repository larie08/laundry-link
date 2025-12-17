// super_admin_reports.js
// Chart.js demo data for static graphs on super_admin_reports.html

document.addEventListener('DOMContentLoaded', function () {
    // Helper to resize canvas to fit parent
    function resizeCanvasToContainer(canvas) {
        canvas.width = canvas.parentElement.offsetWidth;
        canvas.height = canvas.parentElement.offsetHeight;
    }

    // Transaction Chart
    const transactionCanvas = document.getElementById('transactionChart');
    resizeCanvasToContainer(transactionCanvas);
    const transactionCtx = transactionCanvas.getContext('2d');
    new Chart(transactionCtx, {
        type: 'bar',
        data: {
            labels: ['Jan 11', 'Jan 12', 'Jan 13', 'Jan 14', 'Jan 15'],
            datasets: [
                {
                    label: 'Transactions',
                    data: [88, 95, 78, 92, 85],
                    backgroundColor: '#4d7cfe',
                },
                {
                    label: 'Revenue (₱)',
                    data: [17300, 20150, 14850, 18920, 16450],
                    backgroundColor: '#2ed573',
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top' },
                title: { display: true, text: 'Transactions & Revenue (Last 5 Days)' }
            },
            scales: {
                y: { beginAtZero: true }
            }
        }
    });

    // Device Uptime Chart
    const uptimeCanvas = document.getElementById('uptimeChart');
    resizeCanvasToContainer(uptimeCanvas);
    const uptimeCtx = uptimeCanvas.getContext('2d');
    new Chart(uptimeCtx, {
        type: 'line',
        data: {
            labels: ['DEV-001', 'DEV-002', 'DEV-003', 'DEV-004', 'DEV-005'],
            datasets: [
                {
                    label: 'Uptime (%)',
                    data: [99.2, 98.7, 95.4, 99.5, 89.1],
                    borderColor: '#ffa502',
                    backgroundColor: 'rgba(255, 165, 2, 0.2)',
                    fill: true,
                    tension: 0.4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top' },
                title: { display: true, text: 'Device Uptime by Device' }
            },
            scales: {
                y: { beginAtZero: true, max: 100 }
            }
        }
    });

    // Shop Performance Chart
    const performanceCanvas = document.getElementById('performanceChart');
    resizeCanvasToContainer(performanceCanvas);
    const performanceCtx = performanceCanvas.getContext('2d');
    new Chart(performanceCtx, {
        type: 'bar',
        data: {
            labels: ['Makati', 'Mall of Asia', 'City Center', 'Quezon City', 'Mandaluyong'],
            datasets: [
                {
                    label: 'Transactions',
                    data: [1250, 1180, 980, 850, 720],
                    backgroundColor: '#4d7cfe',
                },
                {
                    label: 'Revenue (₱)',
                    data: [245780, 228450, 189750, 165420, 142380],
                    backgroundColor: '#ff4757',
                },
                {
                    label: 'Device Uptime (%)',
                    data: [99.5, 98.7, 99.2, 95.4, 97.8],
                    backgroundColor: '#2ed573',
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top' },
                title: { display: true, text: 'Shop Performance Overview' }
            },
            scales: {
                y: { beginAtZero: true }
            }
        }
    });
});
