// Фото из PIM по публичной ссылке (product.ProductPhoto.public_url). Ссылку
// PIM может отозвать уже после ночного скана — тогда картинка один раз
// переключается на наш прокси из data-fallback-src, а вместе с ней и
// увеличенная версия (data-zoom-src ← data-zoom-fallback-src).
//
// Слушатель — на document в фазе захвата: error у <img> не всплывает, а
// захват видит и картинки из HTMX-фрагментов. Скрипт подключён в <head>,
// чтобы поймать и картинку, упавшую раньше, чем дочитана страница.
document.addEventListener('error', function (event) {
  var img = event.target;
  if (!(img instanceof HTMLImageElement)) return;
  var fallback = img.getAttribute('data-fallback-src');
  if (!fallback) return;
  img.removeAttribute('data-fallback-src');
  var zoomFallback = img.getAttribute('data-zoom-fallback-src');
  if (zoomFallback) {
    img.setAttribute('data-zoom-src', zoomFallback);
    img.removeAttribute('data-zoom-fallback-src');
  }
  img.src = fallback;
}, true);
