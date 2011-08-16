$(document).ready(function() {
    var html_to_prepend = '<div id="gumroad-modal-overlay" style="display: none;">\n	<div id="gumroad-modal">\n		<div id="gumroad-modal-header" class="gradient">\n			<h3>Purchase using Gumroad for <strong>$<span id="gumroad-modal-price">0</span></strong></h3>\n			<a href="#" id="gumroad-modal-close-button">x</a>\n		</div>\n		<form id="gumroad-modal-form" action="" method="post">\n				<p>\n					<label for="card_number">Card Number:</label>\n					<input id="card_number" name="card_number" placeholder="Card number" title="We do <em>not</em> store this! We charge your card and that\'s it." size="30" type="text" />\n				</p>\n\n				<p id="expiry_p">\n					<label for="date_month">Expiry Date:</label>\n						<select id="date_month" name="date_month">\n							<option  value="1">January</option>\n							<option  value="2">February</option>\n							<option  value="3">March</option>\n							<option  value="4">April</option>\n							<option  value="5">May</option>\n							<option  value="6">June</option>\n							<option  value="7">July</option>\n							<option  value="8">August</option>\n							<option  value="9">September</option>\n							<option  value="10">October</option>\n							<option  value="11">November</option>\n							<option  value="12">December</option>\n						  </select> <span>/</span> <select id="date_year" name="date_year">\n							<option  value="2011">2011</option>\n							<option  value="2012">2012</option>\n							<option  value="2013">2013</option>\n							<option  value="2014">2014</option>\n							<option  value="2015">2015</option>\n							<option  value="2016">2016</option>\n							<option  value="2017">2017</option>\n							<option  value="2018">2018</option>\n							<option  value="2019">2019</option>\n							<option  value="2020">2020</option>\n							<option  value="2021">2021</option>\n							<option  value="2022">2022</option>\n							<option  value="2023">2023</option>\n							<option  value="2024">2024</option>\n							<option  value="2025">2025</option>\n							<option  value="2026">2026</option>\n							<option  value="2027">2027</option>\n							<option  value="2028">2028</option>\n							<option  value="2029">2029</option>\n							<option  value="2030">2030</option>\n							</select>\n					</p>\n\n					<p>\n						<label for="card_security_code">Security Code:</label>\n						<input id="card_security_code" name="card_security_code" placeholder="Security code" title="We do <em>not</em> store this either!" size="10" type="text" />\n					</p>\n		</form>\n		<div id="gumroad-modal-footer" class="gradient">\n			<a href="#" id="gumroad-modal-pay-button">Pay</a>\n		</div>\n	</div>\n	<div id="gumroad-modal-extra-copy">\n		<p></p>\n	</div>\n</div>';
    $("head").append('<link href="http://gumroad.com/static/css/gumroad.css" media="screen" rel="stylesheet" type="text/css" />');
    $("head").append('<link rel="stylesheet" href="http://gumroad.com/static/css/tipsy.css" type="text/css" />');
    $("body").prepend(html_to_prepend);

    var item_id = 'xxxxxx';
    
	$("#gumroad-purchase").click(function() {
		show_gumroad_modal();
	});

	$("#gumroad-modal-close-button").click(function() {
		hide_gumroad_modal();
	});
	
	$("#gumroad-modal-pay-button").click(function() {	    
		pay();
	});

	function show_gumroad_modal() {
	    var price = $("#gumroad-purchase").attr("data-price");
	    item_id = $("#gumroad-purchase").attr("data-id");
	    var copy = $("#gumroad-purchase").attr("data-copy");

	    if (price) {
	        $('#gumroad-modal-price').text(price);
	    }
	    
	    if (copy) {
	        $('#gumroad-modal-extra-copy').text(copy);
	    }
	    
        $("#gumroad-modal-overlay").fadeTo("fast", 1.0, function() {
            $("#gumroad-modal-overlay").show();
            $('#card_number').focus();
        });
	}
	
	function hide_gumroad_modal() {
		$("#gumroad-modal-overlay").fadeTo("fast", 0.0, function() {
			$("#gumroad-modal-overlay").hide();
		});
	}
	
	function pay() {
	    var cc_number = $("#card_number").val();
	    var cc_month = $("#date_month").val();
	    var cc_year = $("#date_year").val();
	    var cc_code = $("#card_security_code").val();
	    
	    if (cc_number.length == 0) {
	        alert('Enter a credit card number first.');
	        return;
	    } else if (cc_code.length == 0) {
    	    alert('Enter the card\'s security code.');
    	    return;
    	}
	    
	    $("#gumroad-modal-pay-button").text('Paying securely...');
	    
	    $.post("https://gumroad.appspot.com/api/purchase/", {id: item_id, card_number: cc_number, date_month: cc_month, date_year: cc_year, card_security_code: cc_code}, function(data) {
	        result = data;
	
	        if (data['status'] == 'failure') {
	            $("#gumroad-modal-pay-button").text('Pay');
	            alert(data['error_message']);
	        } else {
	            $("#gumroad-modal-footer").html('<a href="' + data['redirect_url'] + '" id="gumroad-modal-pay-button" target="_blank">Download now</a>');	            
	        }
        });        
	}
});