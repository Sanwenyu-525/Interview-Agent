package demo;

import org.springframework.stereotype.Component;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderService {
    private final OrderRepository orderRepository;

    public OrderService(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    @Transactional
    public Order create(Order order) {
        return orderRepository.save(order);
    }

    public Order find(Long id) {
        return orderRepository.findById(id).orElseThrow();
    }
}

@Component
class OrderMetrics {
}

@org.springframework.context.annotation.Configuration
class OrderConfiguration {
}

@jakarta.persistence.Entity
class Order {
    private Long id;
}
