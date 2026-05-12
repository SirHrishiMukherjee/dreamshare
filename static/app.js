const dreamText = document.getElementById("dreamText");
const dreamPreview = document.getElementById("dreamPreview");

if (dreamText && dreamPreview) {
  dreamText.addEventListener("input", () => {
    dreamPreview.textContent = dreamText.value.trim() || "Your dream will appear here in mild cursive italics.";
  });
}

const playBtn = document.getElementById("playBtn");
const pauseBtn = document.getElementById("pauseBtn");
const dreamVideo = document.getElementById("dreamVideo");
const dreamImage = document.getElementById("dreamImage");
let pulseTimer = null;

function startImagePulse() {
  if (!dreamImage) return;
  let scale = 1;
  pulseTimer = setInterval(() => {
    scale = scale === 1 ? 1.035 : 1;
    dreamImage.style.transition = "transform 1200ms ease";
    dreamImage.style.transform = `scale(${scale})`;
  }, 1200);
}

function stopImagePulse() {
  clearInterval(pulseTimer);
  pulseTimer = null;
  if (dreamImage) dreamImage.style.transform = "scale(1)";
}

if (playBtn) {
  playBtn.addEventListener("click", () => {
    if (dreamVideo) dreamVideo.play();
    else startImagePulse();
  });
}

if (pauseBtn) {
  pauseBtn.addEventListener("click", () => {
    if (dreamVideo) dreamVideo.pause();
    else stopImagePulse();
  });
}

window.addEventListener("load", () => {

    const overlay = document.getElementById("startup-overlay");
    const content = document.getElementById("app-content");

    // already played during this session
    if (sessionStorage.getItem("dreamshareStartupPlayed")) {

        overlay.style.display = "none";
        content.classList.add("visible");

        return;
    }

    // mark startup as played
    sessionStorage.setItem("dreamshareStartupPlayed", "true");

    // play intro animation
    setTimeout(() => {

        overlay.classList.add("fade-out");
        content.classList.add("visible");

        setTimeout(() => {
            overlay.remove();
        }, 1400);

    }, 8500);

});