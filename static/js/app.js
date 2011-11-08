$(document).ready(function() {
    var is_loading = false;
    var loading_bar_background_offset = 0;

    var show_loading = function() {
        is_loading = true;
        $('#loading-indicator').slideDown();
    }

    var hide_loading = function() {
        $('#loading-bar').stop();
        $('#loading-indicator').slideUp();
        is_loading = false;
    }

    window.show_loading = show_loading; 
    window.hide_loading = hide_loading; 
    
    var animate_loading_bar = setInterval(function() {
        if (is_loading) {
            loading_bar_background_offset += 20;
            $('#loading-bar').animate({backgroundPosition: loading_bar_background_offset + 'px 0'}, 600, 'linear');
        }
    }, 600);
});