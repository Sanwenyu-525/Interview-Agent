package demo;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/orders")
public class OrderController {
    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @GetMapping("/{id}")
    public Order getOrder(Long id) {
        return orderService.find(id);
    }

    @PostMapping
    public Order createOrder(Order order) {
        return orderService.create(order);
    }

    @GetMapping("/internal")
    Order internalOrder() {
        return orderService.find(0L);
    }
}
