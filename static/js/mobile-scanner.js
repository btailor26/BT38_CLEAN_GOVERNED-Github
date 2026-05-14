class MobileScanner {
  constructor() {
    this.currentProduct = null;
    this.scanQueue = [];
    this.isBulkMode = false;
    this.isListening = false;
    this.stream = null;
    this.recognition = null;
    
    this.init();
  }
  
  init() {
    this.setupCamera();
    this.setupVoice();
    this.setupEventListeners();
    this.registerServiceWorker();
    this.checkInstallPrompt();
  }
  
  async setupCamera() {
    try {
      const video = document.getElementById('camera-feed');
      if (!video) return;
      
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
      });
      video.srcObject = this.stream;
      
      this.startBarcodeScanning();
    } catch (err) {
      console.error('Camera access failed:', err);
      this.showToast('Camera access denied. Use manual entry.', 'warning');
    }
  }
  
  startBarcodeScanning() {
    if ('BarcodeDetector' in window) {
      const detector = new BarcodeDetector({ formats: ['ean_13', 'ean_8', 'code_128', 'code_39', 'upc_a', 'upc_e'] });
      const video = document.getElementById('camera-feed');
      
      const scan = async () => {
        if (video.readyState === video.HAVE_ENOUGH_DATA) {
          try {
            const barcodes = await detector.detect(video);
            if (barcodes.length > 0) {
              this.handleBarcodeScan(barcodes[0].rawValue);
            }
          } catch (err) {
            console.error('Barcode detection error:', err);
          }
        }
        requestAnimationFrame(scan);
      };
      scan();
    } else {
      this.showToast('Barcode API not supported. Use manual entry.', 'warning');
    }
  }
  
  async handleBarcodeScan(barcode) {
    if (this.currentProduct && this.currentProduct.barcode === barcode) return;
    
    try {
      const response = await fetch(`/api/mobile/sku/${encodeURIComponent(barcode)}`);
      const data = await response.json();
      
      if (data.ok && data.product) {
        this.currentProduct = data.product;
        this.currentProduct.barcode = barcode;
        this.renderProduct();
        this.showToast(`Found: ${data.product.sku}`, 'success');
        
        if (this.isBulkMode) {
          this.addToQueue(1);
        }
      } else if (data.is_carton) {
        this.handleCartonScan(data);
      } else {
        this.showToast('Product not found', 'error');
      }
    } catch (err) {
      console.error('Lookup failed:', err);
      this.showToast('Lookup failed', 'error');
    }
  }
  
  handleCartonScan(data) {
    this.currentProduct = data.product;
    this.currentProduct.is_carton = true;
    this.currentProduct.units_per_carton = data.units_per_carton;
    this.renderProduct();
    this.showCartonPrompt(data.units_per_carton);
  }
  
  showCartonPrompt(unitsPerCarton) {
    const promptEl = document.getElementById('carton-prompt');
    if (promptEl) {
      promptEl.innerHTML = `
        <h3>Master Carton Detected</h3>
        <p>${unitsPerCarton} units per carton. How many cartons?</p>
        <div class="carton-buttons">
          ${[1,2,3,4,5,6,10,20].map(n => 
            `<button class="carton-btn" onclick="scanner.addCartons(${n})">${n}</button>`
          ).join('')}
        </div>
      `;
      promptEl.style.display = 'block';
    }
  }
  
  addCartons(count) {
    if (!this.currentProduct) return;
    const totalUnits = count * this.currentProduct.units_per_carton;
    this.adjustStock(totalUnits, 'add');
    document.getElementById('carton-prompt').style.display = 'none';
  }
  
  renderProduct() {
    const container = document.getElementById('product-card');
    if (!container || !this.currentProduct) return;
    
    const p = this.currentProduct;
    const stockClass = p.available_qty < 5 ? 'danger' : p.available_qty < 20 ? 'warning' : 'positive';
    
    container.innerHTML = `
      <div class="product-sku">${p.sku}</div>
      <div class="product-name">${p.name || 'No name'}</div>
      <div class="stock-display">
        <div class="stock-box">
          <div class="stock-label">Available</div>
          <div class="stock-value ${stockClass}">${p.available_qty}</div>
        </div>
        <div class="stock-box">
          <div class="stock-label">Pending</div>
          <div class="stock-value">${p.pending_qty || 0}</div>
        </div>
        <div class="stock-box">
          <div class="stock-label">Total</div>
          <div class="stock-value">${p.total_qty || p.available_qty}</div>
        </div>
      </div>
    `;
    container.style.display = 'block';
    document.getElementById('no-product').style.display = 'none';
  }
  
  setupEventListeners() {
    document.getElementById('add-1-btn')?.addEventListener('click', () => this.adjustStock(1, 'add'));
    document.getElementById('add-5-btn')?.addEventListener('click', () => this.adjustStock(5, 'add'));
    document.getElementById('set-qty-btn')?.addEventListener('click', () => this.showSetQtyModal());
    document.getElementById('confirm-btn')?.addEventListener('click', () => this.confirmAdjustment());
    document.getElementById('voice-btn')?.addEventListener('click', () => this.toggleVoice());
    document.getElementById('manual-lookup-btn')?.addEventListener('click', () => this.manualLookup());
    
    document.querySelectorAll('.mode-tab').forEach(tab => {
      tab.addEventListener('click', (e) => this.switchMode(e.target.dataset.mode));
    });
    
    document.getElementById('manual-sku')?.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') this.manualLookup();
    });
  }
  
  async adjustStock(qty, operation) {
    if (!this.currentProduct) {
      this.showToast('Scan a product first', 'warning');
      return;
    }
    
    if (this.isBulkMode) {
      this.addToQueue(qty, operation);
      return;
    }
    
    try {
      const response = await fetch('/api/mobile/adjust', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sku: this.currentProduct.sku,
          qty: qty,
          operation: operation
        })
      });
      
      const data = await response.json();
      
      if (data.ok) {
        this.currentProduct.available_qty = data.new_qty;
        this.renderProduct();
        this.showToast(`${operation === 'add' ? '+' : ''}${qty} → ${data.new_qty} units`, 'success');
      } else {
        this.showToast(data.error || 'Adjustment failed', 'error');
      }
    } catch (err) {
      console.error('Adjustment failed:', err);
      this.showToast('Adjustment failed', 'error');
    }
  }
  
  showSetQtyModal() {
    const currentQty = this.currentProduct?.available_qty || 0;
    const newQty = prompt('Set quantity to:', currentQty);
    if (newQty !== null && !isNaN(newQty)) {
      this.adjustStock(parseInt(newQty), 'set');
    }
  }
  
  addToQueue(qty, operation = 'add') {
    if (!this.currentProduct) return;
    
    this.scanQueue.push({
      sku: this.currentProduct.sku,
      qty: qty,
      operation: operation,
      timestamp: Date.now()
    });
    
    this.renderQueue();
    this.showToast(`Added to queue: ${this.currentProduct.sku} +${qty}`, 'success');
  }
  
  renderQueue() {
    const container = document.getElementById('bulk-queue');
    if (!container) return;
    
    if (this.scanQueue.length === 0) {
      container.style.display = 'none';
      return;
    }
    
    container.style.display = 'block';
    const queueItems = this.scanQueue.slice(-10).reverse();
    
    container.innerHTML = `
      <div class="queue-header">
        <span class="queue-count">${this.scanQueue.length} items in queue</span>
        <button class="submit-queue-btn" onclick="scanner.submitQueue()">Submit All</button>
      </div>
      ${queueItems.map(item => `
        <div class="queue-item">
          <span>${item.sku}</span>
          <span>+${item.qty}</span>
        </div>
      `).join('')}
    `;
  }
  
  async submitQueue() {
    if (this.scanQueue.length === 0) return;
    
    try {
      const response = await fetch('/api/mobile/bulk-adjust', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ adjustments: this.scanQueue })
      });
      
      const data = await response.json();
      
      if (data.ok) {
        this.showToast(`Submitted ${data.processed} items`, 'success');
        this.scanQueue = [];
        this.renderQueue();
      } else {
        this.showToast(data.error || 'Bulk submit failed', 'error');
      }
    } catch (err) {
      console.error('Bulk submit failed:', err);
      this.showToast('Bulk submit failed', 'error');
    }
  }
  
  switchMode(mode) {
    this.isBulkMode = mode === 'bulk';
    document.querySelectorAll('.mode-tab').forEach(tab => {
      tab.classList.toggle('active', tab.dataset.mode === mode);
    });
    document.getElementById('bulk-queue').style.display = this.isBulkMode ? 'block' : 'none';
    this.showToast(`Switched to ${mode} mode`, 'success');
  }
  
  setupVoice() {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      document.getElementById('voice-btn')?.style.setProperty('display', 'none');
      return;
    }
    
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    this.recognition = new SpeechRecognition();
    this.recognition.continuous = false;
    this.recognition.interimResults = false;
    this.recognition.lang = 'en-US';
    
    this.recognition.onresult = (event) => {
      const command = event.results[0][0].transcript.toLowerCase();
      this.processVoiceCommand(command);
    };
    
    this.recognition.onend = () => {
      this.isListening = false;
      document.getElementById('voice-btn')?.classList.remove('listening');
    };
  }
  
  toggleVoice() {
    if (!this.recognition) return;
    
    if (this.isListening) {
      this.recognition.stop();
    } else {
      this.recognition.start();
      this.isListening = true;
      document.getElementById('voice-btn')?.classList.add('listening');
      this.showToast('Listening...', 'success');
    }
  }
  
  processVoiceCommand(command) {
    const addMatch = command.match(/add\s+(\d+)/);
    const setMatch = command.match(/set\s+(\d+)/);
    
    if (addMatch) {
      this.adjustStock(parseInt(addMatch[1]), 'add');
    } else if (setMatch) {
      this.adjustStock(parseInt(setMatch[1]), 'set');
    } else if (command.includes('confirm')) {
      this.confirmAdjustment();
    } else if (command.includes('submit')) {
      this.submitQueue();
    } else {
      this.showToast(`Unknown command: ${command}`, 'warning');
    }
  }
  
  async manualLookup() {
    const input = document.getElementById('manual-sku');
    const sku = input?.value?.trim();
    if (!sku) return;
    
    await this.handleBarcodeScan(sku);
    if (input) input.value = '';
  }
  
  showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${message}</span>`;
    container.appendChild(toast);
    
    setTimeout(() => toast.remove(), 3000);
  }
  
  async registerServiceWorker() {
    if ('serviceWorker' in navigator) {
      try {
        await navigator.serviceWorker.register('/static/service-worker.js');
        console.log('Service Worker registered');
      } catch (err) {
        console.error('Service Worker registration failed:', err);
      }
    }
  }
  
  checkInstallPrompt() {
    let deferredPrompt;
    
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;
      
      const promptEl = document.getElementById('install-prompt');
      if (promptEl) {
        promptEl.style.display = 'flex';
        
        document.getElementById('install-btn')?.addEventListener('click', async () => {
          promptEl.style.display = 'none';
          deferredPrompt.prompt();
          const { outcome } = await deferredPrompt.userChoice;
          console.log('Install outcome:', outcome);
          deferredPrompt = null;
        });
        
        document.getElementById('dismiss-install')?.addEventListener('click', () => {
          promptEl.style.display = 'none';
        });
      }
    });
  }
  
  confirmAdjustment() {
    if (this.isBulkMode) {
      this.submitQueue();
    } else {
      this.showToast('Adjustment confirmed', 'success');
    }
  }
}

let scanner;
document.addEventListener('DOMContentLoaded', () => {
  scanner = new MobileScanner();
});
