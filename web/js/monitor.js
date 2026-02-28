// Create Chart instances
const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '75%',
    plugins: {
        legend: { display: false },
        tooltip: { enabled: false }
    },
    animation: { duration: 0 } // Disable animation for performance with frequent updates
};

const colors = {
    cpu: '#6c5ce7',
    ram: '#00cec9',
    gpu: '#fd79a8',
    bg: 'rgba(255, 255, 255, 0.1)'
};

function createDoughnut(ctxId, color) {
    const ctx = document.getElementById(ctxId).getContext('2d');
    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            datasets: [{
                data: [0, 100],
                backgroundColor: [color, colors.bg],
                borderWidth: 0
            }]
        },
        options: chartOptions
    });
}

let cpuChart, ramChart, gpuChart;

document.addEventListener('DOMContentLoaded', () => {
    cpuChart = createDoughnut('cpuChart', colors.cpu);
    ramChart = createDoughnut('ramChart', colors.ram);
    gpuChart = createDoughnut('gpuChart', colors.gpu);
});

// Update function called by app.js when WS message received
function updateCharts(snapshot) {
    if (!snapshot) return;

    // CPU
    if (cpuChart) {
        cpuChart.data.datasets[0].data = [snapshot.cpu_percent, 100 - snapshot.cpu_percent];
        cpuChart.update();
        document.querySelector('#cpuChart').parentElement.querySelector('h3').innerText = `CPU: ${snapshot.cpu_percent}%`;
    }

    // RAM
    if (ramChart) {
        ramChart.data.datasets[0].data = [snapshot.ram_percent, 100 - snapshot.ram_percent];
        ramChart.update();
        document.querySelector('#ramChart').parentElement.querySelector('h3').innerText = `RAM: ${snapshot.ram_used_gb} / ${snapshot.ram_total_gb} GB`;
    }

    // GPU
    if (gpuChart) {
        if (snapshot.gpu_util_percent !== null && snapshot.gpu_util_percent !== undefined) {
            gpuChart.data.datasets[0].data = [snapshot.gpu_util_percent, 100 - snapshot.gpu_util_percent];
            gpuChart.update();
            document.querySelector('#gpuChart').parentElement.querySelector('h3').innerText = `GPU: ${snapshot.gpu_util_percent}%`;
        } else {
            document.querySelector('#gpuChart').parentElement.querySelector('h3').innerText = `GPU: None`;
            gpuChart.data.datasets[0].data = [0, 100];
            gpuChart.update();
        }
    }
}

window.updateCharts = updateCharts;
