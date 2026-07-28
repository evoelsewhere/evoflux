(() => {
  const TOOLS = { pen: "pen", arrow: "arrow", rect: "rect", text: "text", blur: "blur" };
  const COLORS = ["#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7", "#ffffff", "#000000"];
  const STROKE_WIDTHS = { thin: 2, medium: 4, thick: 8 };

  class AnnotationEditor {
    constructor(container) {
      this.container = container;
      this.canvas = null;
      this.ctx = null;
      this.overlayCanvas = null;
      this.overlayCtx = null;
      this.baseImage = null;
      this.annotations = [];
      this.undoneStack = [];
      this.activeTool = TOOLS.pen;
      this.activeColor = COLORS[0];
      this.activeStroke = "medium";
      this.isDrawing = false;
      this.startX = 0;
      this.startY = 0;
      this.currentPath = [];
      this.textInput = null;
      this.scale = 1;
      this.offsetX = 0;
      this.offsetY = 0;
      this._onPointerDown = this._onPointerDown.bind(this);
      this._onPointerMove = this._onPointerMove.bind(this);
      this._onPointerUp = this._onPointerUp.bind(this);
      this._onKeyDown = this._onKeyDown.bind(this);
    }

    open(base64Png) {
      this.container.classList.add("visible");
      this.annotations = [];
      this.undoneStack = [];
      this._loadImage(base64Png);
      document.addEventListener("keydown", this._onKeyDown);
    }

    reopen() {
      if (!this.baseImage) return;
      this.container.classList.add("visible");
      this._setupCanvas();
      this._render();
      document.addEventListener("keydown", this._onKeyDown);
    }

    close() {
      this.container.classList.remove("visible");
      this._removeTextInput();
      document.removeEventListener("keydown", this._onKeyDown);
      if (this.overlayCanvas) {
        this.overlayCanvas.removeEventListener("pointerdown", this._onPointerDown);
        this.overlayCanvas.removeEventListener("pointermove", this._onPointerMove);
        this.overlayCanvas.removeEventListener("pointerup", this._onPointerUp);
        this.overlayCanvas.removeEventListener("pointerleave", this._onPointerUp);
      }
    }

    _loadImage(base64Png) {
      const img = new Image();
      img.onload = () => {
        this.baseImage = img;
        this._setupCanvas();
        this._render();
      };
      img.src = `data:image/png;base64,${base64Png}`;
    }

    _setupCanvas() {
      const wrapper = this.container.querySelector(".annotation-canvas-wrapper");
      wrapper.replaceChildren();

      const containerRect = wrapper.getBoundingClientRect();
      const maxW = containerRect.width - 16;
      const maxH = containerRect.height - 16;
      const imgW = this.baseImage.naturalWidth;
      const imgH = this.baseImage.naturalHeight;
      this.scale = Math.min(1, maxW / imgW, maxH / imgH);
      const displayW = Math.round(imgW * this.scale);
      const displayH = Math.round(imgH * this.scale);

      const canvasContainer = document.createElement("div");
      canvasContainer.className = "annotation-canvas-container";
      canvasContainer.style.position = "relative";
      canvasContainer.style.width = `${displayW}px`;
      canvasContainer.style.height = `${displayH}px`;

      this.canvas = document.createElement("canvas");
      this.canvas.width = displayW;
      this.canvas.height = displayH;
      this.canvas.className = "annotation-canvas";
      this.canvas.style.width = `${displayW}px`;
      this.canvas.style.height = `${displayH}px`;
      this.ctx = this.canvas.getContext("2d");

      this.overlayCanvas = document.createElement("canvas");
      this.overlayCanvas.width = displayW;
      this.overlayCanvas.height = displayH;
      this.overlayCanvas.className = "annotation-overlay";
      this.overlayCanvas.style.width = `${displayW}px`;
      this.overlayCanvas.style.height = `${displayH}px`;
      this.overlayCanvas.style.position = "absolute";
      this.overlayCanvas.style.top = "0";
      this.overlayCanvas.style.left = "0";
      this.overlayCtx = this.overlayCanvas.getContext("2d");

      canvasContainer.appendChild(this.canvas);
      canvasContainer.appendChild(this.overlayCanvas);
      wrapper.appendChild(canvasContainer);

      this.overlayCanvas.addEventListener("pointerdown", this._onPointerDown);
      this.overlayCanvas.addEventListener("pointermove", this._onPointerMove);
      this.overlayCanvas.addEventListener("pointerup", this._onPointerUp);
      this.overlayCanvas.addEventListener("pointerleave", this._onPointerUp);
    }

    _getPos(e) {
      const rect = this.overlayCanvas.getBoundingClientRect();
      return {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      };
    }

    _onPointerDown(e) {
      if (e.button !== 0) return;
      const pos = this._getPos(e);
      this.isDrawing = true;
      this.startX = pos.x;
      this.startY = pos.y;

      if (this.activeTool === TOOLS.pen) {
        this.currentPath = [{ x: pos.x, y: pos.y }];
      } else if (this.activeTool === TOOLS.text) {
        this.isDrawing = false;
        this._showTextInput(pos.x, pos.y);
      }
    }

    _onPointerMove(e) {
      if (!this.isDrawing) return;
      const pos = this._getPos(e);
      if (this.activeTool === TOOLS.pen) {
        this.currentPath.push({ x: pos.x, y: pos.y });
        this._renderOverlay();
      } else if (this.activeTool === TOOLS.arrow || this.activeTool === TOOLS.rect || this.activeTool === TOOLS.blur) {
        this._renderOverlay(pos.x, pos.y);
      }
    }

    _onPointerUp(e) {
      if (!this.isDrawing) return;
      this.isDrawing = false;
      const pos = this._getPos(e);

      if (this.activeTool === TOOLS.pen && this.currentPath.length > 1) {
        this.annotations.push({
          type: "pen",
          path: [...this.currentPath],
          color: this.activeColor,
          strokeWidth: STROKE_WIDTHS[this.activeStroke],
        });
        this.currentPath = [];
      } else if (this.activeTool === TOOLS.arrow) {
        const dx = pos.x - this.startX;
        const dy = pos.y - this.startY;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
          this.annotations.push({
            type: "arrow",
            x1: this.startX, y1: this.startY,
            x2: pos.x, y2: pos.y,
            color: this.activeColor,
            strokeWidth: STROKE_WIDTHS[this.activeStroke],
          });
        }
      } else if (this.activeTool === TOOLS.rect) {
        const w = pos.x - this.startX;
        const h = pos.y - this.startY;
        if (Math.abs(w) > 3 || Math.abs(h) > 3) {
          this.annotations.push({
            type: "rect",
            x: this.startX, y: this.startY,
            w, h,
            color: this.activeColor,
            strokeWidth: STROKE_WIDTHS[this.activeStroke],
          });
        }
      } else if (this.activeTool === TOOLS.blur) {
        const w = pos.x - this.startX;
        const h = pos.y - this.startY;
        if (Math.abs(w) > 3 || Math.abs(h) > 3) {
          this.annotations.push({
            type: "blur",
            x: this.startX, y: this.startY,
            w, h,
          });
        }
      }

      this.undoneStack = [];
      this._renderOverlay();
      this._render();
    }

    _onKeyDown(e) {
      if (e.key === "Escape") {
        if (this.textInput) {
          this._removeTextInput();
        } else {
          this._dispatch("cancel");
        }
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "z") {
        e.preventDefault();
        if (e.shiftKey) this.redo();
        else this.undo();
      }
    }

    _showTextInput(x, y) {
      this._removeTextInput();
      const input = document.createElement("input");
      input.type = "text";
      input.className = "annotation-text-input";
      input.style.left = `${x}px`;
      input.style.top = `${y}px`;
      input.style.color = this.activeColor;
      input.style.fontSize = `${STROKE_WIDTHS[this.activeStroke] * 4 + 10}px`;
      input.placeholder = "Type text…";
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && input.value.trim()) {
          this.annotations.push({
            type: "text",
            x, y,
            text: input.value.trim(),
            color: this.activeColor,
            fontSize: STROKE_WIDTHS[this.activeStroke] * 4 + 10,
          });
          this.undoneStack = [];
          this._removeTextInput();
          this._render();
        } else if (e.key === "Escape") {
          this._removeTextInput();
        }
      });
      const canvasContainer = this.container.querySelector(".annotation-canvas-container");
      if (canvasContainer) {
        canvasContainer.appendChild(input);
      } else {
        this.container.querySelector(".annotation-canvas-wrapper").appendChild(input);
      }
      this.textInput = input;
      requestAnimationFrame(() => input.focus());
    }

    _removeTextInput() {
      if (this.textInput) {
        this.textInput.remove();
        this.textInput = null;
      }
    }

    _render() {
      if (!this.ctx || !this.baseImage) return;
      const { width, height } = this.canvas;
      this.ctx.clearRect(0, 0, width, height);
      this.ctx.drawImage(this.baseImage, 0, 0, width, height);

      for (const ann of this.annotations) {
        if (ann.type === "blur") {
          this._renderBlur(this.ctx, ann);
        }
      }
      for (const ann of this.annotations) {
        if (ann.type === "pen") this._renderPen(this.ctx, ann);
        else if (ann.type === "arrow") this._renderArrow(this.ctx, ann);
        else if (ann.type === "rect") this._renderRect(this.ctx, ann);
        else if (ann.type === "text") this._renderText(this.ctx, ann);
      }
    }

    _renderOverlay(mouseX, mouseY) {
      if (!this.overlayCtx) return;
      const { width, height } = this.overlayCanvas;
      this.overlayCtx.clearRect(0, 0, width, height);

      if (!this.isDrawing) return;

      if (this.activeTool === TOOLS.pen && this.currentPath.length > 1) {
        this._renderPen(this.overlayCtx, {
          path: this.currentPath,
          color: this.activeColor,
          strokeWidth: STROKE_WIDTHS[this.activeStroke],
        });
      } else if (this.activeTool === TOOLS.arrow && mouseX != null) {
        this._renderArrow(this.overlayCtx, {
          x1: this.startX, y1: this.startY,
          x2: mouseX, y2: mouseY,
          color: this.activeColor,
          strokeWidth: STROKE_WIDTHS[this.activeStroke],
        });
      } else if (this.activeTool === TOOLS.rect && mouseX != null) {
        this._renderRect(this.overlayCtx, {
          x: this.startX, y: this.startY,
          w: mouseX - this.startX, h: mouseY - this.startY,
          color: this.activeColor,
          strokeWidth: STROKE_WIDTHS[this.activeStroke],
        });
      } else if (this.activeTool === TOOLS.blur && mouseX != null) {
        this.overlayCtx.save();
        this.overlayCtx.strokeStyle = "#ffffff88";
        this.overlayCtx.lineWidth = 1;
        this.overlayCtx.setLineDash([4, 4]);
        this.overlayCtx.strokeRect(this.startX, this.startY, mouseX - this.startX, mouseY - this.startY);
        this.overlayCtx.restore();
      }
    }

    _renderPen(ctx, ann) {
      ctx.save();
      ctx.strokeStyle = ann.color;
      ctx.lineWidth = ann.strokeWidth;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      ctx.moveTo(ann.path[0].x, ann.path[0].y);
      for (let i = 1; i < ann.path.length; i++) {
        ctx.lineTo(ann.path[i].x, ann.path[i].y);
      }
      ctx.stroke();
      ctx.restore();
    }

    _renderArrow(ctx, ann) {
      const { x1, y1, x2, y2, color, strokeWidth } = ann;
      const angle = Math.atan2(y2 - y1, x2 - x1);
      const headLen = strokeWidth * 4 + 8;

      ctx.save();
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = strokeWidth;
      ctx.lineCap = "round";

      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 6), y2 - headLen * Math.sin(angle - Math.PI / 6));
      ctx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 6), y2 - headLen * Math.sin(angle + Math.PI / 6));
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }

    _renderRect(ctx, ann) {
      ctx.save();
      ctx.strokeStyle = ann.color;
      ctx.lineWidth = ann.strokeWidth;
      ctx.setLineDash([]);
      ctx.strokeRect(ann.x, ann.y, ann.w, ann.h);
      ctx.restore();
    }

    _renderText(ctx, ann) {
      ctx.save();
      ctx.fillStyle = ann.color;
      ctx.font = `bold ${ann.fontSize}px "Segoe UI Variable", "Segoe UI", sans-serif`;
      ctx.textBaseline = "top";
      ctx.shadowColor = "rgba(0,0,0,0.6)";
      ctx.shadowBlur = 3;
      ctx.shadowOffsetX = 1;
      ctx.shadowOffsetY = 1;
      ctx.fillText(ann.text, ann.x, ann.y);
      ctx.restore();
    }

    _renderBlur(ctx, ann) {
      const x = Math.min(ann.x, ann.x + ann.w);
      const y = Math.min(ann.y, ann.y + ann.h);
      const w = Math.abs(ann.w);
      const h = Math.abs(ann.h);
      if (w < 2 || h < 2) return;

      ctx.save();
      const pixelSize = 10;
      const tempCanvas = document.createElement("canvas");
      tempCanvas.width = w;
      tempCanvas.height = h;
      const tempCtx = tempCanvas.getContext("2d");
      tempCtx.drawImage(this.baseImage, x / this.scale, y / this.scale, w / this.scale, h / this.scale, 0, 0, w, h);

      const imgData = tempCtx.getImageData(0, 0, w, h);
      const data = imgData.data;
      for (let py = 0; py < h; py += pixelSize) {
        for (let px = 0; px < w; px += pixelSize) {
          const i = (py * w + px) * 4;
          const r = data[i], g = data[i + 1], b = data[i + 2];
          tempCtx.fillStyle = `rgb(${r},${g},${b})`;
          tempCtx.fillRect(px, py, pixelSize, pixelSize);
        }
      }
      ctx.drawImage(tempCanvas, 0, 0, w, h, x, y, w, h);
      ctx.restore();
    }

    undo() {
      if (!this.annotations.length) return;
      this.undoneStack.push(this.annotations.pop());
      this._render();
      this._renderOverlay();
    }

    redo() {
      if (!this.undoneStack.length) return;
      this.annotations.push(this.undoneStack.pop());
      this._render();
      this._renderOverlay();
    }

    clearAll() {
      if (!this.annotations.length) return;
      this.undoneStack.push(...this.annotations);
      this.annotations = [];
      this._render();
      this._renderOverlay();
    }

    setTool(tool) {
      this.activeTool = tool;
      this._removeTextInput();
      this._dispatch("toolchange", { tool });
    }

    setColor(color) {
      this.activeColor = color;
      this._dispatch("colorchange", { color });
    }

    setStroke(stroke) {
      this.activeStroke = stroke;
      this._dispatch("strokechange", { stroke });
    }

    exportPng() {
      if (!this.canvas) return null;
      this._render();
      return this.canvas.toDataURL("image/png").split(",")[1];
    }

    _dispatch(name, detail) {
      this.container.dispatchEvent(new CustomEvent(`annotation:${name}`, { detail }));
    }
  }

  globalThis.WebBridgeAnnotation = { AnnotationEditor, TOOLS, COLORS, STROKE_WIDTHS };
})();
